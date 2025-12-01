#!/usr/bin/env python3

from test_templates import load_df, read_sparql_templates, df_to_dict, RELATIVE_PATH_TO_TEMPLATE_DIR

import pandas as pd
import os
import json


FNAME = "errors.json"


def read_sparql_template(filename):
  """ returns the content of given scholia template """
  path_to_template_dir = os.path.join(os.getcwd(), *RELATIVE_PATH_TO_TEMPLATE_DIR)
  
  file_path = os.path.join(path_to_template_dir, filename)
  try:
    with open(file_path, 'r', encoding='utf-8') as f:
      content = f.read().strip()
      return content
  except IOError as e:
    print(f"Error reading file {file}: {e}", file=sys.stderr)


def print_results(df_success, df_error, errors):
  pd.set_option('display.max_rows', None)
  print(df_error)
  print("\nThese errors classify as follows:\n")
  print("\n".join(list(f"{error_type}: \n\t{"\n\t".join(erroneous_cases)}" for error_type, erroneous_cases in errors.items())))
  print("\nand they quantify like this:")
  print("\n".join(list(f"{error_type}: {len(erroneous_cases)}" for error_type, erroneous_cases in errors.items())))
  print(f"\nOut of a total of {len(df_error)} cases.")

def classify_errors(df):
  """ 
    classify the errors into known issues: 
    - Missing prefix declaration
      - wd not set, but bd is (and it would work with bd)
      - inside SERVICE call
      - others
    - Out of RAM
    - Timeout
    - extraneous token
     - token "|"
     - other tokens
    - SERVICE request errors
    - other-thread faults
    - bracketing
    - target reuse
    - Others
  """
  types_of_errors = {
    "mpd_bigdata",
    "mpd_service",
    "mpd_other",
    "ram_allocation",
    "timeout",
    "extraneous_token_bar",
    "extraneous_token_other",
    "SERVICE_request",
    "other_thread",
    "bracketing",
    "target_reuse",
    "other"
  }
  errors = {err_type: [] for err_type in types_of_errors}

  for _, error in df.iterrows():
    exception = error['response_content']['exception']
    tname = error['template_name']

    if exception.startswith("Invalid SPARQL query: Prefix") and exception.endswith("was not registered using a PREFIX declaration"):
      # missing prefix declaration
      template = read_sparql_template(tname)
      if "wd" in exception and "PREFIX bd: <http://www.bigdata.com/rdf#>" in template and "PREFIX wd: <http://www.wikidata.org/entity/>" not in template:
        errors["mpd_bigdata"].append(tname)
      elif "SERVICE" in template:
        # this does not forcibly classify correctly, but in most cases will
        errors["mpd_service"].append(tname)
      else:
        errors["mpd_other"].append(tname)
    
    elif exception.startswith("Tried to allocate") and "but only" in exception and exception.endswith("were available"):
      # ram allocation
      errors['ram_allocation'].append(tname)
    
    elif exception.startswith("Error while executing a SERVICE request"):
      # SERVICE request errors
      errors['SERVICE_request'].append(tname)
    
    elif exception.startswith("Invalid SPARQL query: Token \"}\": mismatched input '}' expecting <EOF>"):
      # bracketing
      errors['bracketing'].append(tname)
    
    elif exception.startswith("Invalid SPARQL query: The target ?") and exception.endswith(" of an AS clause was already used in the query body."):
      # target name was reused
      errors['target_reuse'].append(tname)

    elif exception == "Waited for a result from another thread which then failed":
      # other thread
      errors['other_thread'].append(tname)
    
    elif exception.startswith("Operation timed out."):
      # timeout
      errors["timeout"].append(tname)
    
    
    elif exception.startswith("Invalid SPARQL query: Token") and ": extraneous input" in exception:
      if exception.startswith("Invalid SPARQL query: Token \"|\": extraneous input"):
        errors["extraneous_token_bar"].append(tname)
      else:
        errors["extraneous_token_other"].append(tname)

    else:
      # other
      errors['other'].append(tname)

  return errors
    
if __name__ == "__main__":
  df = load_df()
  if df is None:
    raise RuntimeError("No saved data!")

  error_df = df[df['status'] == "error"]
  with open(FNAME, "w") as f:
    json.dump(df_to_dict(error_df), f, indent=2)  # , sort_keys=True)

  succes_df = df[df['status'] == "success"]

  errors = classify_errors(error_df)

  print_results(succes_df, error_df, errors)
  