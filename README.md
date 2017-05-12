# Addok search2steps

[Addok](https://github.com/etalab/addok) plugin to support search an address in two steps.

This plugin run a first query on a sub part of the data and then use the knowledge of this result as context of a second query.

Typically, help ensure results are in a city when you already know witch parts of the address are street, city or postal code.

## Addressed problem

For query:
```
street="Rue Beau Soleil", city="Sains"
```

Vanilla Addok query, found a street but in wrong city:
```
Rue Beau Soleil 44310 Saint-Philbert-de-Grand-Lieu
```

Two steps query, found an approximate street name in right city:
```
Rue Beau Site 35610 Sains
```

## Usage

Use as normal Addok search query, with required `q` and other `limit`, `autocomplete`, etc, including filters.

Search2steps introduce a new parameter: `q0` for preliminary search.

```
http://localhost:7878/search2steps?q0=Brest&q=Rue+du+Restic&limit=5
```

## Configuration

Install the python module, no explicit load is necessary.

The default configuration is:
```python
SEARCH_2_STEPS_STEP1_TYPES = ['municipality']
SEARCH_2_STEPS_STEP1_THRESHOLD = 0.2
SEARCH_2_STEPS_STEP1_LIMIT = 10

SEARCH_2_STEPS_PIVOT_FILTER = 'citycode'
SEARCH_2_STEPS_PIVOT_REWRITE = 'name'

SEARCH_2_STEPS_STEP2_TYPE = 'housenumber'
SEARCH_2_STEPS_STEP2_THRESHOLD = 0.2
```

You can overive it in your configuration file.


## How it works

Search in addok in two steps by:
- Search by q0 and extract a selected field
- Search by q0 + q using the select field as filter

### Step one
Configuration must specify the type of object looked for in this step, it's used as filter in step one.
```python
SEARCH_2_STEPS_STEP1_TYPES = ['municipality', 'locality']
```
Only result with score above the threshold and under this limit will remain available for next step:
```python
SEARCH_2_STEPS_STEP1_THRESHOLD = 0.5
SEARCH_2_STEPS_STEP2_TYPE = 'housenumber'
SEARCH_2_STEPS_STEP1_LIMIT = 10
```

### Pivot
Then specify which field would be extract from step one and use as filter on step two:
```python
SEARCH_2_STEPS_PIVOT_FILTER = 'citycode'
```
q0 will be replaced by this 'normalized' value of result of step one in query of step two:
```python
SEARCH_2_STEPS_PIVOT_REWRITE = 'municipality'
```

### Step two
Only result with score above the threshold will remain in the returned result:
```python
SEARCH_2_STEPS_STEP2_THRESHOLD = 0.2
```

### Fail safe
If two steps query fail, a classic q0 + q query is done.
All result scores are lowered by `SEARCH_2_STEPS_STEP1_THRESHOLD`.

## Example
Initial query:
```
q0=Bordeaux
q=Rue des lilas
limit=1
```

Step one:
```
query:
    q=Bordeaux type=city limit=10
return:
    citycode=33063, name=Bordeaux
    citycode=76117, name=Bordeaux-Saint-Clair
    citycode=33245, name=Lignan-de-Bordeaux
```

Step two:
```
query:
    q="Bordeaux Rue des lilas" citycode=33063 limit 1
    q="Bordeaux-Saint-Clair Rue des lilas" citycode=76117 limit 1
    q="Lignan-de-Bordeaux Rue des lilas" citycode=33245 limit 1
```

## Bonus
The street can be a list of possible candidates when come from a loseley casted address.
```
street? App 6
street? Rue Beau Rosier
postcode: 33000
city: Bordeaux
```

Separate possible alternate street names with a pipe `|`:
```
q0=33000+Bordeaux&q=App+6|Rue+Beau+Rosier
```
