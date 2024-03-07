#!/usr/bin/env poetry run python

# Copyright 2022-2024 Diffblue Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
from typing import Literal

import click
import logging
import ruamel.yaml
from dotenv import load_dotenv
from redash_toolbelt.client import Redash

METAFILE_SUFFIX = ".meta.yaml"


def create_visualization(redash: Redash, data):
    """Add a visualisation to a query.

    For some reason, redash toolbelt doesn't provide this

    I had to copy it from their examples.

    Arguments:
    redash -- Redash toolbelt instance
    data -- JSON data to upload, needs the following shape

    {
        "name": "Query name",
        "description": "Query description",
        "options": { ... },
        "type": "CHART|TABLE|...",
        "query_id": 1 // ID of query to attach to
    }

    returns the newly created visualization, inlcuding the id
    """

    response = redash._post("api/visualizations", json=data)

    return response.json()


def delete_widget(redash: Redash, widget_id):
    """Delete a widget.

    Arguments:
    redash -- Redash toolbelt instance
    widget_id -- ID of widget to delete
    """

    return redash._delete("api/widgets/{}".format(widget_id))


def fix_dashboard_url_id(url: str, existing_dashboards):
    """Fix the ids in links to dashboard urls by looking up the slug

    Arguments:
    url -- The url to fix
    existing_dashboards -- The existing dashboards downloaded from the redash server
    """
    # If URL looks like /dashboards/3-class-summary?p_class={{ id }}
    matches = re.search(r'^/dashboards/([0-9]+)-([a-z0-9-]+)(\?.+|$)', url)
    if not matches:
        return url
    slug = matches.group(2)
    query = matches.group(3)
    try:
        id = [d["id"] for d in existing_dashboards.values() if d["slug"] == slug][0]
        return f"/dashboards/{id}-{slug}{query}"
    except IndexError as e:
        logging.error(f"Could not find dashboard with slug {slug}; {e}")
    return url


def upload_query(redash: Redash, query_name: str, saved_queries,
    existing_queries, existing_dashboards):
    """Upload a query to a redash server

    Returns ID of query uploaded.

    Takes the full dict by name of saved queries from the fetch command and
    existing queries from redash so it can compare them and update any that
    already exist idempotently.

    If the query has parameters that depend on other queries, it will call
    itself recursively to upload those queries first. If it is later called on a
    query that has already been uploaded, it will just return the previous ID
    (which it saves in the "uploaded_id" of the saved queries)

    Arguments:
    redash -- Redash toolbelt instance to upload to
    query_name -- Name of the query to upload
    saved_queries -- Name-indexed dict of queries loaded from disk
    existing_queries -- Name-indexed dict of existing queries from redash server
    existing_dashboards -- Dict of existing dashboards from redash server
    """

    query_data = saved_queries[query_name]

    # If we already have an "uploaded_id", we've already been uploaded, just return the ID.
    if "uploaded_id" in query_data:
        return query_data["uploaded_id"]

    # Change queryName back to queryId on query based parameters
    if "parameters" in query_data["options"]:
        for param in query_data["options"]["parameters"]:
            if param["type"] == "query":
                # Get queryId by calling ourselves recursively
                # - ensures that depended on query is already uploaded
                param["queryId"] = upload_query(
                    redash, param["queryName"], saved_queries, existing_queries,
                    existing_dashboards)
                del param["queryName"]

    # Query does not exist on server, create it
    if query_name not in existing_queries:
        print("Uploading query '%s' ..." %
              (query_name), end="")
        new_query = redash.create_query(query_data).json()
        existing_queries[query_name] = new_query

    # Update it even if just uploaded to ensure published status is correct
    query_id = existing_queries[query_name]["id"]
    print("Updating query '%s' ..." %
          (query_name), end="")
    redash.update_query(query_id, query_data)

    print("done")
    query_data["uploaded_id"] = query_id

    existing_visualisations = \
        {viz["name"]: viz for viz in
         existing_queries[query_name]["visualizations"]}
    for visualization in query_data["visualizations"]:
        visualization["query_id"] = query_id

        for column in visualization["options"].get("columns", []):
            if column.get("displayAs") == "link":
                column["linkUrlTemplate"] = fix_dashboard_url_id(
                    column["linkUrlTemplate"], existing_dashboards)

        if visualization["name"] in existing_visualisations:
            print("  Updating visualization '%s' ..." %
                  (visualization["name"]), end="")
            uploaded_viz = redash.update_visualization(
                existing_visualisations[visualization["name"]]["id"],
                visualization).json()
        else:
            print("  Creating visualization '%s' ..." %
                  (visualization["name"]), end="")

            uploaded_viz = create_visualization(redash, visualization)
        # redash.create_visualization(visualization)

        visualization["uploaded_id"] = uploaded_viz["id"]
        print("done")

    return query_id


def load_saved_queries(datasource: dict):
    """Get queries for a datasource that were saved by fetch command"""

    source_type = datasource["type"]
    query_path = os.path.join("queries", source_type)
    query_filenames = [i[:-len(METAFILE_SUFFIX)]
                       for i in os.listdir(query_path) if
                       i.endswith(METAFILE_SUFFIX)]

    queries = {}
    for filename in query_filenames:
        with open(os.path.join(query_path,
                               filename) + METAFILE_SUFFIX,
                  encoding="utf-8") as metadata_file_handle:
            query_data = ruamel.yaml.load(
                metadata_file_handle, Loader=ruamel.yaml.Loader)

        with open(os.path.join(query_path, filename),
                  encoding="utf-8") as query_file_handle:
            query_data["query"] = query_file_handle.read()

        query_data["data_source_id"] = datasource["id"]

        queries[query_data["name"]] = query_data

    return queries


def upload_queries(redash: Redash, saved_queries, existing_queries, existing_dashboards):
    """Upload queries from filesystem to a redash server

    This will upload all queries found in the "queries" folder on the filesystem
    of the type that matches the datasource and add them to the redash server.

    Arguments:
    redash -- Redash toolbelt instance to upload to
    saved_queries -- The saved queries to be uploaded
    existing_queries -- The existing queries downloaded from the redash server
    existing_dashboards -- The existing dashboards from the redash server
    """
    for query_name in saved_queries:
        upload_query(redash, query_name, saved_queries, existing_queries,
                     existing_dashboards)


def find_data_source(redash: Redash, datasource_name: str = None):
    """Find a datasource to connect queries to

    Will return the first source matching datasource_name if given.

    If no name is given and there is only one, it will be returned.

    If no name is given, and there are many, a list will be printed and the process will exit.

    Arguments:
    redash -- Redash toolbelt instance to upload to
    datasource -- (optional) Data source to connect queries to
    """
    datasources = {i["name"]: i for i in redash.get_data_sources()}
    if datasource_name:
        # Use data source matching name if given (exception if it doesn't exist)
        return datasources[datasource_name]
    elif len(datasources) == 1:
        # If there is only one data source, use it
        return next(iter(datasources.values()))
    else:
        # Print error and list of data sources if we don't know which to use
        logging.error("You must choose a datasource:")
        for source in datasources.values():
            logging.error('  --data-source-name "%s" (%s)' %
                  (source["name"], source["type"]))
        raise RuntimeError("No data source found")


def load_saved_dashboards():
    """Get dashboards that were saved by fetch command"""

    dashboard_path = "dashboards"
    dashboard_filenames = os.listdir(dashboard_path)

    dashboards = {}
    for filename in dashboard_filenames:
        with open(os.path.join(dashboard_path, filename),
                  encoding="utf-8") as file_handle:
            dashboard_data = ruamel.yaml.load(
                file_handle, Loader=ruamel.yaml.Loader)

        dashboards[dashboard_data["name"]] = dashboard_data

    return dashboards


def create_missing_dashboards(redash, saved_dashboards, existing_dashboards):
    """Create dashboards that are missing from the server

    Also adds them to the existing_dashboards dict, so they can be used later.

    Arguments:
    redash -- Redash toolbelt instance to upload to
    saved_dashboards -- The saved dashboards to be checked uploaded
    existing_dashboards -- The existing dashboards downloaded from the redash server
    """

    for name in saved_dashboards:
        if name not in existing_dashboards:
            print("Creating dashboard '%s' ..." %
                  name, end="")
            existing_dashboards[name] = redash.create_dashboard(name)
        else:
            print("Updating dashboard '%s' ..." % name, end="")

        redash.update_dashboard(existing_dashboards[name]['id'], {
            "is_draft": saved_dashboards[name]["is_draft"],
            "tags": saved_dashboards[name]["tags"],
            "dashboard_filters_enabled": saved_dashboards[name]["dashboard_filters_enabled"],
        })
        print(" done")


def update_dashboards(redash, saved_dashboards, existing_dashboards,
    saved_queries) -> Literal[1, 0]:
    """Update dashboard widgets

    Removes all widgets from dashboards then re-adds them from the
    saved_dashboards dict.

    Arguments:
    redash -- Redash toolbelt instance to upload to
    saved_dashboards -- The saved dashboards to be uploaded
    existing_dashboards -- The existing dashboards downloaded from the redash server
    saved_queries -- The queries whose visualisations are to be added to the dashboards
    """
    error = False
    for name in saved_dashboards:
        print("Updating dashboard '%s':" % name)
        if existing_dashboards[name]["widgets"]:
            for w in existing_dashboards[name]["widgets"]:
                print("  Removing widget '%s' of query '%s'" % (w["visualization"]["name"], w["visualization"]["query"]["name"]))
                delete_widget(redash, w["id"])

        for w in saved_dashboards[name]["widgets"]:
            queryName = w["visualization"]["queryName"]
            visualisationName = w["visualization"]["name"]
            print("  Adding widget '%s' of query '%s'" %
                  (visualisationName, queryName))
            query = saved_queries[queryName]
            visualization = next((i for i in query["visualizations"] if i["name"] == visualisationName), None)
            if not visualization:
                error = True
                logging.error(f"Could not find visualisation '{visualisationName}' on query '{queryName}'")
                if visualisationName == "Table":
                    logging.error("Note that the default 'Table' visualisation is not saved unless you edit it manually.")
                continue
            redash.create_widget(
                existing_dashboards[name]["id"], visualization["uploaded_id"], w["text"],
                w["options"]
            )
            print(" done")
    if error:
        logging.info("Dashboards loaded with errors. See above for details.")
        return 1
    else:
        logging.info("Dashboards loaded")
        return 0


@click.command()
@click.option("--redash-url",
              "redash_url",
              required=True,
              envvar="REDASH_URL",
              show_envvar=True,
              prompt="Redash server URL",
              help="The base URL of the redash server, for example http://localhost:5000/",
              )
@click.option(
    "--api-key",
    "api_key",
    required=True,
    envvar="REDASH_API_KEY",
    show_envvar=True,
    prompt="API Key",
    help="User API Key",
)
@click.option(
    "--data-source-name",
    "datasource_name",
    required=False,
    envvar="REDASH_DATA_SOURCE",
    show_envvar=True,
    help="""Name of the redash datasource to attach the queries to. It will be
         queried for its type, then all queries of that type will be uploaded to
         it. Not required if the redash instance has only a single data source.""",
)
@click.option(
    "--log-level",
    "log_level",
    default="INFO",
    help="Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
)
def main(redash_url: str, api_key: str, datasource_name: str, log_level: str):
    """CLI wrapper for push menthod"""

    numeric_log_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_log_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logging.basicConfig(level=numeric_log_level)

    push(redash_url, api_key, datasource_name)


def push(redash_url: str, api_key: str, datasource_name: str):
    """Upload dashboards and queries to a redash instance"""
    redash = Redash(redash_url.rstrip("/"), api_key)

    try:
        datasource: dict = find_data_source(redash, datasource_name)
    except RuntimeError as e:
        exit(1)

    existing_dashboards = {d["name"]: redash.dashboard(d["id"])
                           for d in redash.paginate(redash.dashboards)}

    saved_dashboards: dict = load_saved_dashboards()

    create_missing_dashboards(redash, saved_dashboards, existing_dashboards)

    existing_queries: dict = {q["name"]: redash.get_query(
        q["id"]) for q in redash.paginate(redash.queries)}

    saved_queries: dict = load_saved_queries(datasource)

    upload_queries(redash, saved_queries, existing_queries, existing_dashboards)

    result = update_dashboards(redash, saved_dashboards, existing_dashboards,
                      saved_queries)

    exit(result)

if __name__ == "__main__":
    load_dotenv()
    main()
