#!/usr/bin/env python3

# imports for system and file operations
import os
import sys
import pickle

# imports for api request
import requests
from urllib.parse import quote
import subprocess
from SPARQLWrapper import SPARQLWrapper, JSON # for prompting wqs api

from jinja2 import Environment, FileSystemLoader  # placeholder replacement
import datetime  # also for placeholders
import pandas as pd
import json
import argparse
import time 
import tempfile

# file to save the results to
FILE_BASENAME = "wikidata_results"  
PICKLE_FNAME = FILE_BASENAME + ".pkl"
# the path from this script to the template directory
RELATIVE_PATH_TO_TEMPLATE_DIR = ("..", "..", "templates")


# URLs for API calls
QLEVER_API_URL = "https://qlever.dev/api/wikidata?query="
WQS_API_URL = "https://query.wikidata.org/sparql"

# subprocess call in parts (<port> will be replaced with given port)
QLEVER_CALL = ["curl", "-s", "<port>", "--data-urlencode", "query="]

# internal entity/QID dict that maps a query type to a set of QIDs
ENTITIES = {
  "author": ["Q2399315"],
  "authors": ["Q20980928", "Q24290415", "Q24390693", "Q26720269"],
  "award": ["Q18357422", "Q37922"],
  "catalogue": ["Q51467536"],
  "chemical": ["Q159683"],
  "chemical-class": ["Q41581"],
  "chemical-element": ["Q623"],
  "cito": ["Q96479983"],
  "clinical-trial": ["Q64650701"],
  "complex": ["Q409796"],
  "country": ["Q142"],
  "countries": ["Q114", "Q258", "Q1036", "Q954", "Q1013", "Q963", "Q1030", "Q953"],
  "dataset": ["Q69644056"],
  "disease": ["Q41112"],
  "event": ["Q56579271"],
  "event-series": ["Q105695391"],
  "gene": ["Q18030793"],
  "language": ["Q1860"],
  "lexeme": ["L1473010"],
  "license": ["Q14947546"],
  "location": ["Q791", "Q1748"],
  "mesh": ["D028441"],
  "ontology": ["Q55118285"],
  "organization": ["Q19375720", "Q835960"],
  "organizations": ["Q24283660", "Q19845644"],
  "pathway": ["Q50294491"],
  "podcast": ["Q124363332"],
  "podcast-episode": ["Q67590634"],
  "podcast-season": ["Q69152103"],
  "printer": ["Q118455415"],
  "project": ["Q27949537"],
  "protein": ["Q21109365"],
  "publisher": ["Q5168538", "Q118455415"],
  "series": ["Q924044"],
  "software": ["Q1659584", "Q5140318"],
  "sponsor": ["Q1377836"],
  "taxon": ["Q25485"],
  "topic": ["Q202864"],
  "topics": [
    "Q202864", "Q5227350", "Q2539", "Q18972821", "Q18970437",
    "Q18970321", "Q18970360", "Q18972580", "Q18972329",
    "Q184199", "Q19049584"
  ],
  "use": ["Q1659584"],
  "uses": ["Q1659584", "Q112270642"],
  "venue": ["Q939416"],
  "venues": ["Q15751424", "Q15757725", "Q15751497"],
  "wikiproject": ["Q114364300"],
  "work": ["Q27932040"],
  "works": ["Q24699014", "Q27230311"]
}


def load_df():
  """Load existing DataFrame from pickle or return None if not possible"""
  if os.path.exists(PICKLE_FNAME):
    with open(PICKLE_FNAME, 'rb') as f:
      df = pickle.load(f)
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
    f.flush()  # Force Python to immediately write buffered data to OS
    os.fsync(f.fileno())  # Force OS to immediately write data to disk
  
  os.replace(fname_tmp, fname)

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

def insert_wikidata_entity(template: str, entities: list[str]):
  """ uses jinja2 replacement to generate a valid query from a template by filling in the entities, languages and datetime """
  env = Environment(
      loader=FileSystemLoader(os.path.join(os.getcwd(), *RELATIVE_PATH_TO_TEMPLATE_DIR)),  # directory containing sparql-helpers.sparql
      autoescape=False
  )

  template = env.from_string(template)

  def get_entity(entities, pos):
    """ safely get entity at pos """
    if pos < len(entities):
      return entities[pos]
    else:
      return entities[0]

  out = template.render(
      q=entities[0],              # replaces {{q}} placeholders
      q1=entities[0],             # replaces {{q1}} placeholders
      q2=get_entity(entities, 1), # replaces {{q2}} placeholders
      q3=get_entity(entities, 2), # replaces {{q3}} placeholders
      q4=get_entity(entities, 3), # replaces {{q4}} placeholders
      qs=entities,                # replaces {% for q in qs %} placeholders
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

def get_response_from_endpoint(query: str, port: str, url: str):
  """ prompts the API to get the response from the query """
  start = time.perf_counter()
  ### wqs endpoint
  if url == WQS_API_URL:
    response_decoded = get_response_wqs(url, query)
    # it would be best to also stream the response to a tmpfile
    # and safely decode it later, but the api functionality provided by wqs doesn't allow me to do it the same way
    end = time.perf_counter()
  ### qlever and other endpoints
  elif url != "":
      response_decoded = safely_fetch_response(query, url)
      end = time.perf_counter()
      # response_decoded = safe_decode_of_tmpfile(tmp)
  ### local qlever endpoint
  else:
    qlever_call = QLEVER_CALL[:-1] + [QLEVER_CALL[-1] + query]
    qlever_call = map(lambda x: port if x == "<port>" else x, qlever_call)
    with tempfile.NamedTemporaryFile(mode="w+", suffix=".json") as tmp:
      try:
        subprocess.run(
            qlever_call,
            stdout=tmp,
            stderr=subprocess.PIPE,
            check=True
        )
      except Exception:
        raise RuntimeError(f"Not possible to fetch result from local endpoint at port {port}! Are you sure the endpoint is up?")
      end = time.perf_counter()
      response_decoded = safe_decode_of_tmpfile(tmp)
  
  elapsed = end - start
  print("...", end="")
  return response_decoded, elapsed

def safely_fetch_response(query, url):
  """ fetch the response safely, by streaming it into a tmpfile first and then decoding it """
  # print("\n"*10)
  # print(query)
  # print(url)
  # print("\n"*10)
  with tempfile.NamedTemporaryFile(mode="wb+") as tmp:
    try:
      with requests.get(url + quote(query), stream=True) as r:
        r.raise_for_status()
        for chunk in r.iter_content(chunk_size=1024 * 1024):
          if chunk:
            tmp.write(chunk)
    except Exception:
      raise RuntimeError(f"Not possible to fetch a response from the endpoint at url {url}! Are you sure the endpoint is up?")
    return safe_decode_of_tmpfile(tmp)

def safe_decode_of_tmpfile(tmp):  
  """ 
  decode the answer only if enough memory is available
  if the answer is too large, it means qlever successfully returned a result and didn't fail
  """
  tmp.flush()
  file_size = os.path.getsize(tmp.name)

  available_ram = available_ram_bytes()

  if available_ram is not None:
    # the amount of memory needed will be larger than the filesize, also the amount of available memory might fluctuate
    estimated_needed = int(file_size * 50)
    if estimated_needed > available_ram:
      print("Answer too large to decode safely. ", end="")
      return { 
          "status": "too_large",
          "file_size_bytes": file_size,
          "estimated_needed_bytes": estimated_needed,
          "available_ram_bytes": available_ram,
        }

    tmp.seek(0)
    response_decoded = json.load(tmp)
    return response_decoded

def available_ram_bytes():
  """ estimates amount of RAM available to process """
  if hasattr(os, "sysconf"):
      try:
          page_size = os.sysconf("SC_PAGE_SIZE")
          available_pages = os.sysconf("SC_AVPHYS_PAGES")
          return page_size * available_pages
      except (ValueError, OSError):
          pass
  return None

def should_skip_template(df, entities, template_name, overwrite_all, overwrite_error, overwrite_success, cli_templates, exceptions):
  """ Check if template should be skipped """
  # don't skip templates, that have been explicitly passed as a CLI arguments
  # if templates have been explicitly passed skip all others
  if cli_templates is not None:
    return False if template_name.split("/")[-1] in cli_templates else True

  if exceptions is not None: 
    if template_name.split("/")[-1] in exceptions:
      return True 
  
  if overwrite_all or df.empty:
    return False
  
  mask = (df['entities'] == ", ".join(map(str, entities))) & (df['template_name'] == template_name)
  if overwrite_error:
    mask = mask & (df['status'] == 'success')
  if overwrite_success:
    mask = mask & (df['status'] != 'success')
  return mask.any()

def find_suitable_entities(template_name):
  """ truncate template_name, and find associated entities in internal dict """
  # truncation ex: software-curation_missing-describes-use.sparql >>> software-curation
  template_type = template_name.split("_")[0]
  entities = ENTITIES.get(template_type, None)
  if entities is None:
    # more general truncation, if the specic version didnt return anything 
    # ex: software-curation >>> software
    template_type = template_type.split("-")[0]
    entities = ENTITIES.get(template_type, None)
    if entities is None:
      # only warn because there is templates where None is fine, because they dont need to replace any qids
      print(f"WARNING: No suitable entity in internal dictionairy for template: {template_name}!")
      entities = [None]
  return entities

def print_results(df):
  """ Print results """
  print(df['status'].value_counts())
  print(f"\nTotal: {len(df)}")
  pd.set_option('display.max_rows', None)
  print(df)

def df_to_dict(df):
  """ Turn df into dict indexed by template_name """    
  result = {}
  for _, row in df.iterrows():
    template_name = row['template_name']
    row = row.drop(['template_name'])
    data = row.to_dict()
    result[template_name] = data
  return result

def filter_response(response_content, response_time, entities, template_name, result_limit=-1):
  """ removes all unwanted information from the response and puts it into the correct format to save it """  
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
  'entities': ", ".join(map(str, entities)),
  'template_name': template_name,
  'status': status,
  'response_time': response_time,
  'response_content': response_content
  }
  return result_dict

def run_template(template_name, template, entities, port, url, print_query=False, result_limit=-1):
  """ insert wikidata entity in template and prompt a service, then return the filtered result """
  query = insert_wikidata_entity(template, entities)
  if print_query:
    print(query)
  response, response_time = get_response_from_endpoint(query, port, url)
  return filter_response(response, response_time, entities, template_name, result_limit)

def update_df(df, result_dict):
  """ update the dataframe with a result from a single template """
  # remove old entry
  if not df.empty:
    mask = (df['entities'] == result_dict['entities']) & (df['template_name'] == result_dict['template_name'])
    if mask.any():
      df.drop(df[mask].index, inplace=True)
    
  # add new entry
  new_row = pd.DataFrame([result_dict])
  df = pd.concat([df, new_row], ignore_index=True)
  return df

def parse_cli_args():
  parser = argparse.ArgumentParser(description=
    'Test scholias SPARQL templates against Wikidata endpoints. \
    By default the queries are evaluated by a local endpoint at port: host.docker.internal:7001.\
    The results are saved in the file: "wikidata_results.pkl" and can be exported to json.\
    If a query result with the same QIDs, the same endpoint and the same template name is found in the results, it will be skipped.')
  parser.add_argument('--qids', type=str, default=None, nargs="+", 
                      help='Wikidata QID(s), that will be filled in to the template(s) (default: will use internal dict to find a qid that returns a non-empty result)')
  parser.add_argument('--templates', type=str, nargs='+', default=None,
                      help='Test only the given template(s)')
  parser.add_argument('--exceptions', type=str, nargs='+', default=None,
                      help='Excepts the given template(s) from the tests')
  parser.add_argument('--retest-all', action='store_true',
                      help='Retest queries that otherwise would be skipped')
  parser.add_argument('--retest-error', action='store_true',
                      help='Retest saved results instead of skipping, but only if the previous status was not "success"')
  parser.add_argument('--retest-success', action='store_true',
                      help='Retest saved results instead of skipping, but only if the previous status was "success"')
  parser.add_argument('--port', type=str, default=None,
                      help='Port at which a Wikidata endpoint is up')
  parser.add_argument('--use-qlever-endpoint', action='store_true',
                      help='Evaluate the queries with the online endpoint at URL: "https://qlever.dev/api/wikidata?query=" (Qlever endpoint)')
  parser.add_argument('--use-wqs-endpoint', action='store_true',
                      help='Evaluate the queries with the online endpoint at URL: "https://query.wikidata.org/sparql" (WQS enpoint)')
  parser.add_argument('--use-other-online-endpoint', type=str, default=None,
                      help='URL at which a Wikidata endpoint is up')
  parser.add_argument('--print-query', action='store_true',
                      help='Print queries before sending them to the endpoint')
  parser.add_argument('--print-results', action='store_true',
                      help='Print the saved results and exit')
  parser.add_argument('--export-to-json', action='store_true',
                      help='Export the results to Json and exit')
  
  return parser.parse_args()


if __name__ == "__main__":
  # cli parsing
  args = parse_cli_args()
  entities = args.qids
  cli_templates = args.templates
  exceptions = args.exceptions
  overwrite_all = args.retest_all
  overwrite_error = args.retest_error
  overwrite_success = args.retest_success
  print_query = args.print_query
  
  # check for conflicting endpoints
  def check_url(url):
    if url != "":
      raise RuntimeError("Exiting because more than one endpoint has been given!")
    
  url = ""
  port = "host.docker.internal:7001"
  if args.use_qlever_endpoint:
    url = QLEVER_API_URL 
  if args.use_wqs_endpoint:
    check_url(url)
    url = WQS_API_URL
  if args.use_other_online_endpoint is not None:
    check_url(url)
    url = args.use_other_online_endpoint
  if args.port is not None:
    check_url(url)
    port = args.port

  # load previously saved data
  df = load_or_create_df()

  # print results and quit
  if args.print_results:
    print_results(df)
    sys.exit(0)

  # export to Json and quit
  if args.export_to_json:
    fname = f"{FILE_BASENAME}.json"
    with open(fname, "w") as f:
      json.dump(df_to_dict(df), f, indent=2)
      print(f"Saved information in json format in: {fname}")
    sys.exit(0)


  templates = list(read_templates_from_template_dir())

  ### main testing loop
  for n_processed, (template_name, template) in enumerate(templates):
    # find proper entities/qids
    if entities is None:
      entities = find_suitable_entities(template_name)

    print(f"{n_processed + 1}/{len(templates)}: {template_name} using entities {', '.join(map(str, entities))}. ", end="", flush=True)
    
    if should_skip_template(df, entities, template_name, overwrite_all, overwrite_error, overwrite_success, cli_templates, exceptions):
      print("SKIPPED")
      continue

    result = run_template(template_name, template, entities, port, url, print_query, result_limit=1)
    df = update_df(df, result)
    save_df(df)
    print(f"{result['status'].upper()}")

  print_results(df)
