#!/usr/bin/env python3

# imports for system and file operations
import os
import sys
import pickle  # for saving results

# imports for api request
import requests
from urllib.parse import quote
import subprocess
from SPARQLWrapper import SPARQLWrapper, JSON # for prompting wqs api

from jinja2 import Environment, FileSystemLoader
import datetime  # also for placeholders
import pandas as pd  # for storing results
import json  # for reading the api results
import argparse  # argument parsing
import time  # for timer

# file to save the results to
FILE_BASENAME = "wikidata_results"  
PICKLE_FNAME = FILE_BASENAME + ".pkl"
# the path from this script to the template directory
RELATIVE_PATH_TO_TEMPLATE_DIR = ("..", "..", "templates")

# URLs for API calls
QLEVER_API_URL = "https://qlever.dev/api/wikidata?query="
WQS_API_URL = "https://query.wikidata.org/sparql"

################################# change port here >  <
QLEVER_CALL = ["curl", "-s", "host.docker.internal:7001", "--data-urlencode", "query="]


def load_df():
  """Load existing DataFrame from pickle or return None if not possible"""
  if os.path.exists(PICKLE_FNAME):
    with open(PICKLE_FNAME, 'rb') as f:
      df = pickle.load(f)
    print(f"Loaded existing df\r", end="")
    return df
  else:
    return None

def load_or_create_df():
  """Load existing DataFrame from pickle or create new one"""
  df = load_df()
  if df is None:
    return pd.DataFrame()
  else:
    return df

def save_df(df, fname=None):
  """Save DataFrame to pickle file"""
  if fname == None:
    fname = PICKLE_FNAME
  
  fname_tmp = fname + ".tmp"  # use tmp file and rename later to prevent corruption from multiple accesses at once
  
  with open(fname_tmp, 'wb') as f:
    pickle.dump(df, f)
    f.flush()  # Force Python to write buffered data to OS
    os.fsync(f.fileno())  # Force OS to write data to disk
  
  os.replace(fname_tmp, fname)
  print("Saved df\r", end="")

def read_templates_from_template_dir():
  """ yields the filename and file content of scholia's sparql templates """
  path_to_template_dir = os.path.join(os.getcwd(), *RELATIVE_PATH_TO_TEMPLATE_DIR)

  files = os.listdir(path_to_template_dir)

  # filter out all non-sparql files
  sparql_files = filter(lambda file: file.endswith(".sparql"), files)
  
  return read_sparql_templates(sparql_files)

def read_sparql_templates(fnames):
  path_to_template_dir = os.path.join(os.getcwd(), *RELATIVE_PATH_TO_TEMPLATE_DIR)
  for fname in fnames:
    fpath = os.path.join(path_to_template_dir, fname)
    try:
      with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read().strip()
        yield (fname, content)
    except IOError as e:
      print(f"Error reading file {fname}: {e}", file=sys.stderr)

def insert_wikidata_entity(template: str, entity: str):
  """ uses jinja2 replacement to generate a valid query from a template by filling in the entity """
  env = Environment(
      loader=FileSystemLoader(os.path.join(os.getcwd(), *RELATIVE_PATH_TO_TEMPLATE_DIR)),  # directory containing sparql-helpers.sparql
      autoescape=False
  )

  template = env.from_string(template)

  out = template.render(
      q=entity,      # replaces {{q}} placeholders
      q1=entity,     # replaces {{q1}} placeholders
      q2=entity,     # replaces {{q2}} placeholders
      q3=entity,     # replaces {{q3}} placeholders
      q4=entity,     # replaces {{q4}} placeholders
      qs=[entity],   # replaces {% for q in qs %} placeholders
      languages=["en", "mul"],
      datetime=datetime
  )
  return out

def get_response_wqs(endpoint_url, query):
  """ function provided by wqs to prompt wqs """
  user_agent = "WDQS-example Python/%s.%s" % (sys.version_info[0], sys.version_info[1])
  sparql = SPARQLWrapper(endpoint_url, agent=user_agent)
  sparql.setQuery(query)
  sparql.setReturnFormat(JSON)
  return sparql.query().convert()

def get_response_https(query: str, url: str=QLEVER_API_URL):
  """ prompts the API to get the response from the query """
  start = time.perf_counter()
  if url == QLEVER_API_URL:
    response = requests.get(url + quote(query))
    response_decoded = response.json()
  elif url == WQS_API_URL:
    response_decoded = get_response_wqs(url, query)
  end = time.perf_counter()
  elapsed = end - start
  return response_decoded, elapsed

def get_response_local(query: str):
  """ prompts local (running) qlever server to get a response from the query """
  qlever_call = QLEVER_CALL[:-1] + [QLEVER_CALL[-1] + query]
  start = time.perf_counter()
  response = subprocess.check_output(qlever_call)
  response_decoded = json.loads(response.decode("utf-8"))
  end = time.perf_counter()
  elapsed = end - start

  return response_decoded, elapsed

def should_skip_template(df, entity, template_name, overwrite_all, overwrite_error, overwrite_success, cli_templates, exceptions):
  """
    Check if template should be skipped 
    - if its already in the df and overwrite_all is false
    - if overwrite_error is true and status is "succes"
    - if overwrite_succes is true and status is not "succes"
  """
  # don't skip templates, that have been explicitly passed as a CLI arguments
  # if templates have been explicitly passed skip all others
  if cli_templates is not None:
    return False if template_name.split("/")[-1] in cli_templates else True

  if exceptions is not None: 
    return True if template_name.split("/")[-1] in exceptions else False
  
  if overwrite_all or df.empty:
    return False
  
  mask = (df['entity'] == entity) & (df['template_name'] == template_name)
  if overwrite_error:
    mask = mask & (df['status'] == 'success')
  if overwrite_success:
    mask = mask & (df['status'] != 'success')
  return mask.any()

def print_results(df, entity):
  """ Print results for a specific entity """
  entity_data = df[df['entity'] == entity] if 'entity' in df.columns else df
  
  if len(entity_data) == 0:
    print(f"No data for entity {entity}")
    return
  
  print(f"\nResults for {entity}:")
  print(entity_data['status'].value_counts())
  print(f"\nTotal: {len(entity_data)}")
  pd.set_option('display.max_rows', None)
  print(df)

def df_to_dict(df, wikidata_entity=None):
  """ Turn all entries belonging to a given entity (QID) to a dict index by template_name """
  if wikidata_entity is not None:
    df = df[df['entity'] == wikidata_entity]
    
  result = {}
  for _, row in df.iterrows():
    template_name = row['template_name']
    # Get all columns except 'entity' and 'template_name'
    row = row.drop(['entity', 'template_name'])
    data = row.to_dict()
    result[template_name] = data
  
  return result

def filter_response(response_content, response_time, entity, template_name, result_limit=-1):
  """ decodes and removes all unwanted information from the response """  
  status = "error" if "exception" in response_content.keys() else "success" 
  results = response_content.pop('results', None)
  if results is not None:
    response_content['results'] = results['bindings']
    if result_limit > 0:
      response_content['results'] = response_content['results'][:result_limit]

  # throw out the following info from the response
  response_content.pop('head', None)
  response_content.pop('resultsize', None) 
  runtime_info = response_content.pop('runtimeInformation', None)
  response_content.pop('status', None)
  
  # result data, that will be saved
  result_dict = {
  'entity': entity,
  'template_name': template_name,
  'status': status,
  'response_time': response_time,
  'response_content': response_content
  }
  return result_dict

def run_template(template_name, template, entity, print_query=False, url="", result_limit=-1):
  """ insert wikidata entity in template and prompt a service, then return the filtered result """
  query = insert_wikidata_entity(template, entity)
  if print_query:
    print(query)
  #try:
  if url != "":
    response, response_time = get_response_https(query, url)
  else:
    response, response_time = get_response_local(query)
  # except Exception as e:
  #   if e == KeyboardInterrupt:
  #     raise KeyboardInterrupt()
  #   print("Couldn't get a result from the query! Either the server could not be reached or the reply couldn't be decoded in json format.")
  #   response = {"exception": "Couldn't fetch result"}
  #   response_time = -1
  return filter_response(response, response_time, entity, template_name, result_limit)

def update_df(df, result_dict):
  """ update the dataframe with a result from a single template """
  # remove old entry (only if overwrite is true)
  if not df.empty:
    mask = (df['entity'] == result_dict['entity']) & (df['template_name'] == result_dict['template_name'])
    if mask.any():
      df.drop(df[mask].index, inplace=True)
    
  # add new entry
  new_row = pd.DataFrame([result_dict])
  df = pd.concat([df, new_row], ignore_index=True)
  return df

def parse_cli_args():
  parser = argparse.ArgumentParser(description=
    'Test scholias SPARQL templates against Wikidata entities. \
    By default this script expects a local qlever server at localhost:7001.\
    The options --use-qlever-api or --use-wqs-api will instead prompt the official qlever/wqs instance.')
  parser.add_argument('--entity', type=str, default="Q18618629", 
                      help='Wikidata entity (default: Q18618629 - Denny Vrandecic)')
  parser.add_argument('--print-only', action='store_true',
                      help='Just prints the saved results, without testing any templates')
  parser.add_argument('--print-query', action='store_true',
                      help='Prints the query given to qlever before executing it.')
  parser.add_argument('--template', type=str, nargs='+', default=None,
                      help='tests only the given template(s)')
  parser.add_argument('--exceptions', type=str, nargs='+', default=None,
                      help='omits the given template(s) from the tests')
  parser.add_argument('--overwrite-all', action='store_true',
                      help='Overwrite saved results for this entity instead of skipping')
  parser.add_argument('--overwrite-error', action='store_true',
                      help='Overwrite saved results for this entity instead of skipping, but only if the previous status was not "success".')
  parser.add_argument('--overwrite-success', action='store_true',
                      help='Overwrite saved results for this entity instead of skipping, but only if the previous status was "success".')
  parser.add_argument('--save-as-json', action='store_true',
                      help='Save the results belonging to this wikidata entry in human readable json format.')
  parser.add_argument('--use-qlever-api', action='store_true',
                      help='Prompt the qlever api via https instead of the locally running qlever server.')
  parser.add_argument('--use-wqs-api', action='store_true',
                      help='Prompt the wqs api via https instead of the locally running qlever server.')
  
  return parser.parse_args()


if __name__ == "__main__":
  # cli parsing
  args = parse_cli_args()
  wikidata_entity = args.entity
  cli_templates = args.template
  exceptions = args.exceptions
  print_query = args.print_query
  overwrite_all = args.overwrite_all
  overwrite_error = args.overwrite_error
  overwrite_success = args.overwrite_success
  if args.use_qlever_api:
    url = QLEVER_API_URL 
  elif args.use_wqs_api:
    url = WQS_API_URL
  else:
     url = ""

  # loading df
  df = load_or_create_df()

  if args.print_only:
    print_results(df, wikidata_entity)
    sys.exit(0)

  if args.save_as_json:
    if df.empty or wikidata_entity not in df["entity"].unique():
      raise RuntimeError(f"DF doesn't contain information on this entity ({wikidata_entity})!")
    fname = FILE_BASENAME + f"_{wikidata_entity}.json"
    with open(fname, "w") as f:
      json.dump(df_to_dict(df, wikidata_entity), f, indent=2)  # , sort_keys=True)
      print(f"Saved information in json format in: {fname}")
    sys.exit(0)


  # skip already saved templates
  templates = list(read_templates_from_template_dir())
  templates_to_process = [t for t in templates if not should_skip_template(df, wikidata_entity, t[0], overwrite_all, overwrite_error, overwrite_success, cli_templates, exceptions)]

  # print how many skipped how many to go
  skipped = len(templates) - len(templates_to_process)
  print(f"Skipping {skipped} already processed templates")
  
  if templates_to_process == []:
    print("All templates already processed. Use --overwrite-all or --overwrite-error.")
  else:
    print(f"Processing {len(templates_to_process)} templates for entity {wikidata_entity}")


  for processed, (template_name, template) in enumerate(templates_to_process):
    print(f"{processed + 1}/{len(templates_to_process)}: {template_name}", end="\r")
    result = run_template(template_name, template, wikidata_entity, print_query, url=url, result_limit=1)
    df = update_df(df, result)
    save_df(df)
    print(f"{result['status']}: {template_name}")

  print_results(df, wikidata_entity)
