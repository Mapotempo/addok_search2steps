import falcon
from falcon_multipart.middleware import MultipartMiddleware

from addok.config import config
from addok.core import search
from addok.helpers.text import EntityTooLarge

from addok_csv import View, BaseCSV, log_query, log_notfound
import itertools
import hashlib

import math

def register_http_middleware(middlewares):
    middlewares.append(MultipartMiddleware())


def register_http_endpoint(api):
    api.add_route('/search2steps', Search2Steps())
    api.add_route('/search2steps/csv', CSVSearch2steps())

def preconfigure(config):
    config.SEARCH_2_STEPS_STEP1_TYPES = ['municipality', 'locality']
    config.SEARCH_2_STEPS_STEP1_THRESHOLD = 0.2
    config.SEARCH_2_STEPS_STEP1_LIMIT = 10
    config.SEARCH_2_STEPS_STEP2_LIMIT = 10

    config.SEARCH_2_STEPS_PIVOT_FILTER = 'citycode'
    config.SEARCH_2_STEPS_PIVOT_REWRITE = ['postcode', 'name']

    config.SEARCH_2_STEPS_STEP2_TYPE = 'housenumber'
    config.SEARCH_2_STEPS_STEP2_THRESHOLD = 0.2
    config.SEARCH_2_STEPS_STEP2_PENALITY_MULTIPLIER = 0.5
    config.SEARCH_2_STEPS_FULL_TEXT_PENALITY_MULTIPLIER = 0.7

def multiple_search(queries, **args):
    if len(queries) > 0:
        return max([search(query, **args) for query in queries], key=lambda x: x and len(x) > 0 and x[0].score or 0)
    else:
        return []

def search2steps_step1(config, query1, limit, **filters):
    filters_step_1 = filters.copy()
    ret = []
    for type in config.SEARCH_2_STEPS_STEP1_TYPES:
        filters_step_1['type'] = type
        ret += search(query1, limit=limit, autocomplete=False, **filters_step_1)
    return ret

def search2steps(config, query1, queries2, autocomplete, limit, **filters):
    # Fetch the join value
    join_value = threshold = results = None

    # Run step 1 query
    # Query1 = "postalcode city" => "33000 Bordeaux"
    results1 = search2steps_step1(config, query1, config.SEARCH_2_STEPS_STEP1_LIMIT, **filters)
    if len(queries2) == 0:
        ret = results1[0:limit]
        results_full = search(query1, limit=limit, autocomplete=autocomplete, **filters)
    else:
        ret = []
        if results1:
            params_steps_2 = []
            # Collect step 1 results
            for result in results1:
                score_step_1 = result.score

                query_step_1 = " ".join([ str(result.__getattr__(pivot)) for pivot in config.SEARCH_2_STEPS_PIVOT_REWRITE ])

                if config.SEARCH_2_STEPS_PIVOT_FILTER in filters and filters[config.SEARCH_2_STEPS_PIVOT_FILTER]:
                    join_value = filters[config.SEARCH_2_STEPS_PIVOT_FILTER]
                    threshold = 1
                else:
                    join_value = result.__getattr__(config.SEARCH_2_STEPS_PIVOT_FILTER)
                    threshold = result.score

                if join_value and threshold > config.SEARCH_2_STEPS_STEP1_THRESHOLD:
                    params_steps_2.append((join_value, query_step_1, score_step_1))

            # Make results uniq
            params_steps_2 = set(params_steps_2)

            # Run steps 2 queries
            for join_value, query_step_1, score_step_1 in params_steps_2:
                # Set step 2 query filter from step 1 result
                filters_step_2 = filters.copy()
                filters_step_2[config.SEARCH_2_STEPS_PIVOT_FILTER] = join_value # SEARCH_2_STEPS_PIVOT_FILTER = citycode
                filters_step_2['type'] = config.SEARCH_2_STEPS_STEP2_TYPE

                # Mixup queries2 with results of step 1
                # Queries2 = "105 boulevard Mac Donald"
                # query_step_1 = "75019 Paris"
                # "street result_postalcode_step1 result_city_step_1" => "105 Boulevard mac Donald 75019 Paris"
                results_step_2 = multiple_search([q + ' ' + query_step_1 for q in queries2], limit=config.SEARCH_2_STEPS_STEP2_LIMIT, autocomplete=autocomplete, **filters_step_2)
                append = False
                if results_step_2:
                    for result_step_2 in results_step_2:
                        if result_step_2.score > config.SEARCH_2_STEPS_STEP2_THRESHOLD:
                            # Lower step 2 score depending on score in step1
                            result_step_2.score = 2 * (math.cos(math.sqrt(score_step_1) - 1) - 0.5) * result_step_2.score
                            append = True
                            ret.append(result_step_2)
                if not append:
                    # No usable result from steps 2, use steps 1 result
                    # Lower the score
                    result.score *= config.SEARCH_2_STEPS_STEP2_PENALITY_MULTIPLIER
                    if result.score > config.SEARCH_2_STEPS_STEP2_THRESHOLD:
                        ret.append(result)

        # Full text search to get some kind of fallback results
        results_full = multiple_search([q + ' ' + query1 for q in queries2], limit=limit, autocomplete=autocomplete, **filters)

    for result in results_full:
        result_id = get_id(result)
        # lower score of full text search results if not in step 2
        exist = [ret_value for ret_value in ret if get_id(ret_value) == result_id]
        if len(exist) == 0:
            result.score *= config.SEARCH_2_STEPS_FULL_TEXT_PENALITY_MULTIPLIER

        ret.append(result)

    if ret:
        # Sort results to make highest scores appears first
        # Then make result uniq in case of duplicates
        return make_uniq(sorted(ret, key=lambda k: k.score, reverse=True))
    else:
        return results1[0:limit]

def make_uniq(duplicates):
    uniq = []
    ids = []
    for value in duplicates:
        currentId = get_id(value)
        if value.id not in ids:
            uniq.append(value)
            ids.append(currentId)
    return uniq

def get_id(value):
    return value.id if value.id else generateMD5Id(value)

def generateMD5Id(value):
    encodedValue = (
        value.city
        + value.postcode
        + value.street
        + str(value.housenumber)
        + value.type
        + str(value.score)
    ).encode()
    return hashlib.md5(encodedValue).digest()

class Search2Steps(View):

    def on_get(self, req, resp, **kwargs):
        # Separate parameters get from request
        q0 = req.get_param('q0')
        q0 = q0.split('|') if q0 and len(q0.strip()) > 0 else []
        q = req.get_param('q')
        q = q.split('|') if q and len(q.strip()) > 0 else []

        # q = "postalcode city" => "33000 Bordeaux"
        # q0 = "street" => "37 Rue des lilas"

        if len(q) == 0 and len(q0) == 0:
            raise falcon.HTTPBadRequest('Missing query', 'Missing query')
        limit = req.get_param_as_int('limit') or 5  # use config
        autocomplete = req.get_param_as_bool('autocomplete')
        if autocomplete is None:
            # Default is True.
            # https://github.com/falconry/falcon/pull/493#discussion_r44376219
            autocomplete = True
        lon, lat = self.parse_lon_lat(req)
        center = None
        if lon and lat:
            center = (lon, lat)
        filters = self.match_filters(req)

        try:
            if len(q0) == 0:
                # Full text query
                # => "37 Rue des lilas 33000 bordeaux"
                results = multiple_search(q, limit=limit, autocomplete=False, lat=lat, lon=lon, **filters)
                query = '|'.join(q)
            else:
                # 2Steps query
                # => q0 = "33000 Bordeaux"
                # => q = "37 Rue des lilas"
                results = search2steps(self.config, q0[0], q, autocomplete=autocomplete, limit=limit, lat=lat, lon=lon, **filters)
                query = '|'.join(q0) + ' ' + ('|').join(q)
        except EntityTooLarge as e:
            raise falcon.HTTPRequestEntityTooLarge(str(e))

        if not results:
            log_notfound(query)
        log_query(query, results)
        self.to_geojson(req, resp, results, query=query, filters=filters, center=center, limit=limit)


class CSVSearch2steps(BaseCSV):

    base_headers = ['latitude', 'longitude', 'result_label', 'result_score',
                    'result_type', 'result_id', 'result_housenumber', 'result_citycode']

    def compute_fieldnames(self, req, file_, content, rows):
        fieldnames, columns = super(CSVSearch2steps, self).compute_fieldnames(req, file_, content, rows)
        self.columns0 = req.get_param_as_list('columns0') or []
        for column in self.columns0:
            if column not in fieldnames:
                msg = "Cannot found column '{}' in columns {}".format(column, fieldnames)
                raise falcon.HTTPBadRequest(msg, msg)
        return fieldnames, columns

    def process_row(self, req, row, filters, columns):
        row_split = dict([(k, v and v.split('|')) for k, v in row.items()])
        # Generate all combinations
        # We don't want None in a join.
        q0 = list(filter(lambda x: x and x != '', [' '.join([l or '' for l in i]) for i in itertools.product(*[row_split[k] or [None] for k in self.columns0])]))
        q = list(filter(lambda x: x and x != '', [' '.join([l or '' for l in i]) for i in itertools.product(*[row_split[k] or [None] for k in columns])]))
        filters = self.match_row_filters(row, filters)
        lat_column = req.get_param('lat')
        lon_column = req.get_param('lon')
        if lon_column and lat_column:
            lat = row.get(lat_column)
            lon = row.get(lon_column)
            if lat and lon:
                filters['lat'] = float(lat)
                filters['lon'] = float(lon)

        try:
            if len(q0) == 0:
                # Full text query
                # => "37 Rue des lilas 33000 bordeaux"
                results = multiple_search(q, autocomplete=False, limit=1, **filters)
                query = '|'.join(q)
            else:
                # 2Steps query
                # => q0 = "33000 Bordeaux"
                # => q = "37 Rue des lilas"
                results = search2steps(self.config, q0[0], q, autocomplete=False, limit=1, **filters)
                query = '|'.join(q0) + ' ' + ('|').join(q)
        except EntityTooLarge as e:
            raise falcon.HTTPRequestEntityTooLarge(str(e))

        log_query(query, results)
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
            self.add_extra_fields(row, result)
        else:
            log_notfound(query)
