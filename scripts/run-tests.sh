#!/bin/bash

bash_on_failure() {
    set +o xtrace  # do not show what's being executed
    RED='\033[0;31m'
    NC='\033[0m' # No Color

    echo
    printf "${RED}There was an error running tests. Fix them and try again with: bash scripts/run-tests.sh [--keepdb]${NC}\n"
    bash
    exit
}


set -e  # stops the script on error

usage="$(basename "$0") [-h | --help] [--ci] [--bash-on-finish] [--keepdb] -- runs project's tests
where:
    -h | --help  show this help text
    --ci  runs tests in CI mode (it will show extra info)
    --bash-on-finish  opens bash interpreter when the script finishes running.
                      Useful to re-run tests faster locally.
    --keepdb  keeps database after running tests. Skips requirements (re)install.
    "

ci=false
bash_on_finish=false
keepdb=false

# Parse options. Note that options may be followed by one colon to indicate
# they have a required argument
if ! options=$(getopt -o h -l ci,bash-on-finish,keepdb,help -- "$@")
then
    # Error, getopt will put out a message for us
    exit 1
fi

set -- $options

while [ $# -gt 0 ]
do
    # Consume next (1st) argument
    case $1 in
    -h|--help)
      echo "$usage"; exit ;;
    --ci)
      ci="true" ;;
    --bash-on-finish)
      bash_on_finish="true" ;;
    --keepdb)
      keepdb="true" ;;
    (--)
      shift; break;;
    (-*)
      echo "$0: error - unrecognized option $1" 1>&2; exit 1;;
    (*)
      break;;
    esac
    # Fetch next argument as 1st
    shift
done

set -o xtrace  # shows what's being executed

apk add git
pip install -r requirements/test.txt

if [ "$ci" = true ] ; then
    flake8 .
fi

if [ "$bash_on_finish" = true ] ; then
    set +e  # do not stop the script on error
fi


if [ $? -eq 1 ] && [ "$bash_on_finish" = true ]; then
    bash_on_failure
fi

if [ "$ci" = true ] ; then
    pytest --log-level=2 --cov
    if [ $? -eq 1 ] && [ "$bash_on_finish" = true ]; then
        bash_on_failure
    fi
    coverage report -m
else
    # No --pdb here. This is the path CI uses (unit_test.yml passes --keepdb), and
    # --pdb drops into an interactive IPython debugger on the FIRST failure; in a
    # non-interactive container it reads EOF and quits the session, so the run
    # reported on 5 of 368 tests and hid the other 33. Pass --pdb explicitly on the
    # command line when debugging locally.
    if [ "$keepdb" = true ] ; then
        pytest --log-level=2 --reuse-db
    else
        pytest --log-level=2
    fi
    if [ $? -eq 1 ] && [ "$bash_on_finish" = true ]; then
        bash_on_failure
    fi
fi
python manage.py makemigrations --check --dry-run

if [ $? -eq 1 ] && [ "$bash_on_finish" = true ]; then
    bash_on_failure
elif [ "$bash_on_finish" = true ] ; then
    set +o xtrace  # do not show what's being executed
    bash
fi
