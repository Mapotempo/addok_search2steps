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

Search2steps introduce a new required parameter: `q0` for preliminary search.

```
http://localhost:7878/search2steps?q0=Brest&q=Rue+du+Restic&limit=5
```

## Configuration

Load the plugin in Addok config file:
```python
import re
import sys
sys.path.append('/srv/addok/addok') # abs path to config file directory

def ON_LOAD():
  import search2steps
```

Add the plugin to the API end points:
```python
API_ENDPOINTS = [
    …
    ('/search2steps/', 'search2steps'),
    ('/search2steps/csv', 'search2steps.csv'),
    …
]
```

Configure the plugin:
```python
SEARCH_2_STEPS_STEP1_TYPE = 'city'
SEARCH_2_STEPS_STEP1_THRESHOLD = 0.5
SEARCH_2_STEPS_STEP1_LIMIT = 10
SEARCH_2_STEPS_PIVOT_FILTER = 'citycode'
SEARCH_2_STEPS_PIVOT_REWRITE = 'city'
SEARCH_2_STEPS_STEP2_THRESHOLD = 0.2
```

## How it works

Search in addok in two steps by:
- Search by q0 and extract a selected field
- Search by q0 + q using the select field as filter

### Step one
Configuration must specify the type of object looked for in this step, it's used as filter in step one.
```python
SEARCH_2_STEPS_STEP1_TYPE = 'city'
```
Only result with score above the threshold and under this limit will remain available for next step:
```python
SEARCH_2_STEPS_STEP1_THRESHOLD = 0.5
SEARCH_2_STEPS_STEP1_LIMIT = 10
```

### Pivot
Then specify which field would be extract from step one and use as filter on step two:
```python
SEARCH_2_STEPS_PIVOT_FILTER = 'citycode'
```
q0 will be replaced by this 'normalized' value of result of step one in query of step two:
```python
SEARCH_2_STEPS_PIVOT_REWRITE = 'city'
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
q0=Bordeaux q="Rue des lilas" limit=1
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
