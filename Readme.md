# DISTRIBUTIVES MONGO API

REST API service to work with DistributivesDB (based on MongoDB).

## How to start:

- Separate MongoDB service may be used also instead.
- Environment variables should be provided for connection: `MONGO_URL`, `MONGO_USER`, `MONGO_PASSWORD`, `MONGO_DB`, `MONGO_CONNECT_ATTEMPTS`
- Module should be started with `gunicorn` daemon. Example: `python3 -m gunicorn oc_distributives_mongo_api.wsgi:app -b 0.0.0.0:5400`

## Tests

The real *MongoDB* should be used for tests since the emulator can not provide some constratints used in the models.
