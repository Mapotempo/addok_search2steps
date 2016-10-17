from werkzeug.wrappers import Response
from werkzeug.exceptions import BadRequest
from addok.server import View, BaseCSV, log_query, log_notfound
from addok.core import search

def search2steps_step1(config, query1, limit, **filters):
    filters_step_1 = filters.copy()
    filters_step_1['type'] = config.SEARCH_2_STEPS_STEP1_TYPE
    return search(query1, limit=limit, autocomplete=False, **filters_step_1)

def search2steps(config, query1, query2, autocomplete, limit, **filters):
    # Fetch the join value
    join_value = threshold = results = None

    # Run step 1 query
    results = search2steps_step1(config, query1, config.SEARCH_2_STEPS_STEP1_LIMIT, **filters)
    if not query2:
        return results[0:limit]

    if results:
        params_steps_2 = []
        # Collect step 1 results
        for result in results:
            query_step_1 = result.__getattr__(config.SEARCH_2_STEPS_PIVOT_REWRITE)

            if config.SEARCH_2_STEPS_PIVOT_FILTER in filters and filters[config.SEARCH_2_STEPS_PIVOT_FILTER]:
                join_value = filters[config.SEARCH_2_STEPS_PIVOT_FILTER]
                threshold = 1
            else:
                join_value = result.__getattr__(config.SEARCH_2_STEPS_PIVOT_FILTER)
                threshold = result.score

            if join_value and threshold > config.SEARCH_2_STEPS_STEP1_THRESHOLD:
                params_steps_2.append((join_value, query_step_1))

        # Make results uniq
        params_steps_2 = set(params_steps_2)
        ret = []
        # Run steps 2 queries
        for join_value, query_step_1 in params_steps_2:
            # Set step 2 query filter from step 1 result
            filters_step_2 = filters.copy()
            filters_step_2[config.SEARCH_2_STEPS_PIVOT_FILTER] = join_value
            results_step_2 = search(query2 + ' ' + query_step_1, limit=limit, autocomplete=autocomplete, **filters_step_2)
            append = False
            if results_step_2:
                for result_step_2 in results_step_2:
                    if result_step_2.score > config.SEARCH_2_STEPS_STEP2_THRESHOLD:
                        append = True
                        ret.append(result_step_2)
            if not append:
                # No usable result from steps 2, use steps 1 result
                # Lower the score
                result.score *= config.SEARCH_2_STEPS_STEP1_THRESHOLD
                if result.score > config.SEARCH_2_STEPS_STEP2_THRESHOLD:
                    ret.append(result)

        if ret:
            # Sort and limit results for all queries
            return sorted(ret, key=lambda k: k.score, reverse=True)[0:limit]

    # Can't run steps 2, run a classic plain text search
    results = search(query2 + ' ' + query1, limit=limit, autocomplete=autocomplete, **filters)
    for result in results:
        # Lower the score
        result.score *= config.SEARCH_2_STEPS_STEP1_THRESHOLD
    return results

class Search2Steps(View):

    endpoint = 'search2steps'

    def get(self):
        q0 = self.request.args.get('q0', '')
        if not q0:
            return Response('Missing query part one (q0=)', status=400)
        q = self.request.args.get('q', '')
        try:
            limit = int(self.request.args.get('limit'))
        except (ValueError, TypeError):
            limit = 5
        try:
            autocomplete = int(self.request.args.get('autocomplete')) == 1
        except (ValueError, TypeError):
            autocomplete = True
        try:
            lat = float(self.request.args.get('lat'))
            lon = float(self.request.args.get('lon',
                        self.request.args.get('lng')))
        except (ValueError, TypeError):
            lat = None
            lon = None
        filters = self.match_filters()
        results = search2steps(self.config, q0, q, autocomplete=autocomplete, limit=limit, lat=lat, lon=lon, **filters)
        if not results:
            log_notfound(q0 + ' ' + q)
        log_query(q0 + ' ' + q, results)
        return self.to_geojson(results, query=q0 + ' ' + q)

class CSVSearch2steps(BaseCSV):

    endpoint = 'search2steps.csv'
    base_headers = ['latitude', 'longitude', 'result_label', 'result_score',
                    'result_type', 'result_id', 'result_housenumber', 'result_citycode']

    def compute_fieldnames(self):
        super(CSVSearch2steps, self).compute_fieldnames()
        self.columns0 = self.request.form.getlist('columns0')
        for column in self.columns0:
            if column not in self.fieldnames:
                raise BadRequest("Cannot found column '{}' in columns {}".format(column, self.fieldnames))

    def process_row(self, row):
        # We don't want None in a join.
        q0 = ' '.join([row[k] or '' for k in self.columns0])
        q = ' '.join([row[k] or '' for k in self.columns])
        filters = self.match_row_filters(row)
        lat_column = self.request.form.get('lat')
        lon_column = self.request.form.get('lon')
        if lon_column and lat_column:
            lat = row.get(lat_column)
            lon = row.get(lon_column)
            if lat and lon:
                filters['lat'] = float(lat)
                filters['lon'] = float(lon)
        results = search2steps(self.config, q0, q, autocomplete=False, limit=1, **filters)
        log_query(q0 + ' ' + q, results)
        if results:
            result = results[0]
            row.update({
                'latitude': result.lat,
                'longitude': result.lon,
                'result_label': str(result),
                'result_score': round(result.score, 2),
                'result_type': result.type,
                'result_id': result.id,
                'result_housenumber': result.housenumber,
                'result_citycode': result.citycode,
            })
            self.add_fields(row, result)
        else:
            log_notfound(q0 + ' ' + q)
