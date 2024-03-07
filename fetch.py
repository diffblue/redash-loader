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

# Based on redash_toolbelt's save_queries example

import os
import re

import click
import ruamel.yaml
from dotenv import load_dotenv
from redash_toolbelt.client import Redash

from util import make_filename

METAFILE_SUFFIX = ".meta.yaml"

QUERY_META_FIELDS = [
    "name",
    "description",
    "is_archived",
    "is_draft",
    "is_favourite",
    "options",
    "schedule",
    "tags"
]

VISUALIZATIONS_IGNORE_FIELDS = {
    "id",
    "updated_at",
    "created_at"
}

DASHBOARD_FIELDS = [
    "slug",
    "name",
    "layout",
    "dashboard_filters_enabled",
    "options",
    "is_archived",
    "is_draft",
    "tags"
]

DASHBOARD_WIDGET_IGNORE_FIELDS = {
    "dashboard_id",
    "id",
    "updated_at",
    "created_at",
    "query",
    "visualization"
}

def save_queries(datasources: dict, queries: dict, pathToQueries: str):
    """Save redash queries to disk as yaml and meta files.

    Arguments:
    datasources -- dict of datasources from redash, indexed by id. Used to find type of query.
    queries -- List of queries to save
    pathToQueries -- directory on filesystem to put files
    """
    yaml = ruamel.yaml.YAML()

    for query in queries.values():
        source: dict = datasources[query["data_source_id"]]

        # path looks like queries/type/name.format
        path: str = os.sep.join([pathToQueries, source["type"], make_filename(
            query["name"]) + "." + source["syntax"]])

        os.makedirs(os.sep.join([pathToQueries, source["type"]]), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(query["query"])
            if not query["query"].endswith("\n"):
                f.write("\n")

        # Object that becomes the meta file
        metadata: dict = {}

        # Load existing metadata with round trip loader if it exists
        try:
            with open(path + METAFILE_SUFFIX, "r",
                      encoding="utf-8") as orig_meta_file:
                metadata = ruamel.yaml.load(
                    orig_meta_file, ruamel.yaml.RoundTripLoader)

        except FileNotFoundError:
            pass

        # Change queryId to queryName on query based parameters
        if "parameters" in query["options"]:
            for param in query["options"]["parameters"]:
                if param["type"] == "query":
                    param["queryName"] = queries[param["queryId"]]["name"]
                    del param["queryId"]

        # Store main metadata fields
        for field in QUERY_META_FIELDS:
            if field in query:
                # only overwrite fields if they have changed to improve YAML round trip
                if metadata.get(field) != query.get(field):
                    metadata[field] = query[field]

        # Store visualizations
        if "visualizations" in query:
            for viz in query["visualizations"]:
                for field in VISUALIZATIONS_IGNORE_FIELDS:
                    if field in viz:
                        del viz[field]

                for column in viz["options"].get("columns", []):
                    if column.get("displayAs") == "link":
                        column["linkUrlTemplate"] = re.sub(r'(^/dashboards/)[0-9]+(-[a-z0-9-]+\?.+|$)', r'\g<1>0\g<2>', column["linkUrlTemplate"])

            metadata["visualizations"] = [i for i in query["visualizations"] if i != {
                "type": "TABLE",
                "name": "Table",
                "options": {},
                "description": ""
            }]

            metadata["visualizations"].sort(key=lambda i: i.get("name"))

        # Write to disk
        with open(path + METAFILE_SUFFIX, "w", encoding="utf-8") as meta_file:
            yaml.dump(metadata, meta_file)


def save_dashboards(dashboards: list, pathToDashboards: str):
    """Save redash dashboards to disk as yaml and meta files.

    Arguments:
    dashboards -- List of dashboards to save
    pathToDashboards -- directory on filesystem to put files
    """
    yaml = ruamel.yaml.YAML()
    os.makedirs(pathToDashboards, exist_ok=True)

    for dashboard in dashboards:
        path: str = os.sep.join(
            [pathToDashboards, make_filename(dashboard["name"]) + ".yaml"])

        # Object that becomes the meta file
        dashboard_data: dict = {}

        # Load existing dashboard_data with round trip loader if it exists
        try:
            with open(path, "r", encoding="utf-8") as orig_meta_file:
                dashboard_data = ruamel.yaml.load(
                    orig_meta_file, ruamel.yaml.RoundTripLoader)

        except FileNotFoundError:
            pass

        for i in DASHBOARD_FIELDS:
            if dashboard_data.get(i, None) != dashboard[i]:
                dashboard_data[i] = dashboard[i]

        dashboard_data["widgets"] = []
        dashboard["widgets"].sort(key=lambda i: (i["options"]["position"]["row"],i["options"]["position"]["col"]))
        for orig_widget in dashboard["widgets"]:
            filtered_widget = {k: orig_widget[k] for k in orig_widget.keys() if k not in DASHBOARD_WIDGET_IGNORE_FIELDS}
            if "visualization" in orig_widget:
                filtered_widget["visualization"] = {
                    "name": orig_widget["visualization"]["name"],
                    "queryName": orig_widget["visualization"]["query"]["name"]
                }
            dashboard_data["widgets"].append(filtered_widget)

        with open(path, "w", encoding="utf-8") as dashboard_file:
            yaml.dump(dashboard_data, dashboard_file)


@click.command()
@click.option("--redash-url",
              "redash_url",
              envvar="REDASH_URL",
              show_envvar=True,
              prompt="URL of the Redash instance")
@click.option(
    "--api-key",
    "api_key",
    required=True,
    envvar="REDASH_API_KEY",
    show_envvar=True,
    prompt="API Key",
    help="User API Key",
)
def main(redash_url: str, api_key: str):

    pathToQueries = "queries"
    pathToDashboards = "dashboards"

    redash: Redash = Redash(redash_url.rstrip("/"), api_key)
    datasources: dict = {
        i["id"]: i for i in redash.get_data_sources()}
    queries: dict = {q["id"]: redash.get_query(
        q["id"]) for q in redash.paginate(redash.queries)}
    save_queries(datasources, queries, pathToQueries)

    dashboards = [redash.get_dashboard(d["id"])
                  for d in redash.paginate(redash.dashboards)]
    save_dashboards(dashboards, pathToDashboards)


if __name__ == "__main__":
    load_dotenv()
    main()
