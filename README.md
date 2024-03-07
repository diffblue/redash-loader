# Redash loader

Allows you to save queries from Redash as plain text (YAML) files so that they can be committed to
git etc. to easily collaborate on them.

## Installation

Install poetry - https://python-poetry.org/

Run `poetry install`. This will configure a python virtualenv with all the dependencies you need.

## Usage

To download the queries, type:

```bash
./fetch.py
```

> On Linux, these scripts seem to need to be run through `poetry`, e.g.
> `poetry run python fetch.py`

It will need prompt you for the URL and API key for the redash instance. You can get the API key
from your user profile page.

To save having to type the key and URL in each time, you can supply them on the command line with
the options `--api-key` and `--redash-url` or set the environment variables `REDASH_API_KEY` and
`REDASH_URL`.

You can also set the environment variables using a `.env` file. Copy `.env.example` and edit as
appropriate.

This will download a series of files to a directory structure in the current directory,
for example:

```text
queries
├── json
│   ├── list_reports.yaml
│   └── list_reports.yaml.meta.yaml
└── pg
    ├── list_database.sql
    └── list_database.sql.meta.yaml
```

Queries are in a `queries` folder, then separated by type - e.g. `json` for REST API type queries,
`pg` for PostgreSQL etc.

Each query is saved with an appropriate file type, usually `.sql` or `.yaml`, which contains the text
of the query as you edit it in Redash, as well as a `.meta.yaml` file which contains the query's
name, description and other settings. The name of the file is derived from the name of the query.

If you have a directory structure already and an empty redash instance which you wish to insert
the queries into, run:

```bash
./push.py
```

This will query redash for a list of data sources, and if there is only one it will upload all the
queries whose type matches, attaching them to that data source. If there is more than one it will
return a list of data sources. You must pick one and pass it as a parameter `--data-source-name` or
you can use the environment variable `REDASH_DATA_SOURCE`, for example:

```bash
./push.py --data-source-name "My datasource name"
```

It will only insert queries for one datasource at a time. It will ignore queries not of the same
type - for example if you select a PostgreSQL data source it will only upload queries in teh `pg`
folder.

## Cool Features

* Formatting of the query file should match what is entered in Redash exactly.
* Formatting of the meta file can be prettified and the fetch script will try not to change it
  as much as possible if you re-download. For example, you can change quoting types or insert
  comments and it will try to preserve them. Only fields that have changed will be updated, and
  their formats may be affected in that case.
* The shebang line includes `poetry run python` so the script should run correctly without needing
  to worry about python virtualenvs etc. You can still call `python script.py` normally if you need
  to.

## Known bugs

These are unlikely to be fixed - they are things to be aware of that can be coped with:

* Pushing only works with a pre-configured data source. Saving data source configuration is not
  supported because it is setup-specific.
* Queries must be uniquely named for their type, or they will clobber other queries on disk. This is
  not detected, no warnings will be given.
* If you rename a query in redash it will get a new name on disk and the old one will not be
  deleted.

## Developer notes

The scripts contain [python type hints](https://docs.python.org/3/library/typing.html). These can be
validated using the mypy tool as follows:

```bash
poetry run mypy [script name]
```

----
Copyright 2022-2024 Diffblue Limited

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
