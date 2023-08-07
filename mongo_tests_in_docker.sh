#!/bin/bash

# to make client and database parameters equal
export MONGO_DB="${MONGO_INITDB_DATABASE}"
export MONGO_USER="${MONGO_INITDB_ROOT_USERNAME}"
export MONGO_PASSWORD="${MONGO_INITDB_ROOT_PASSWORD}"

echo "Starting Mongo for tests purpose"
/usr/local/bin/docker-entrypoint.sh mongod >> /dev/null 2>&1 &

# test mongo connection
echo "Waiting until Mongo is available"
for (( i=0; i<10; i++ )); do
    echo "Attempt ${i}"
    sleep 5
    if [ ! -z "$(echo 'db.runCommand("ping").ok' | mongo "${MONGO_DB}" --quiet | grep '1')" ]
    then
        echo "Mongo daemon started from apptempt No ${i}"
        break
    fi
done

if (( i>=10 ))
then
    echo "Mongo daemon start error"
    exit 1
fi


python3 -m coverage run -m unittest discover -v
RC="${?}"
pwd
python3 -m coverage xml --include=./distributives_mongo_api/app/routes.py -o /build/coverage.xml
test -f /build/coverage.xml || echo '<xml />' > /build/coverage.xml

echo "Stopping mongo"
kill $(pidof mongod)

echo "Waiting Mongo to stop"

for (( i=0; i<10; i++ )); do
    echo "Attempt ${i}"
    sleep 5
    if [ -z "$(pidof mongod)" ]
    then
        echo "Mongo daemon stopped from apptempt No ${i}"
        break
    fi
done

# kill the daemon by hard way
if (( i>=10 ))
then
    echo "Mongo daemon stop failed, killing hardcorely"
    kill -9 $(pidof mongod)
fi

exit "${RC}"
