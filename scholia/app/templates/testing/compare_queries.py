#!/usr/bin/env python3

import os
import argparse
from test_templates import run_template, read_sparql_templates


QLEVER_API_URL = "https://qlever.dev/api/wikidata?query="
WQS_API_URL = "https://query.wikidata.org/sparql"


def print_differences(wqs, qlever, ignore_label=False):
  if len(wqs) > 0:
    entity = wqs[0]['entity']
  else:
    entity = qlever[0]['entity']

  print(f"Timings on entity {entity}:         ")
  for res in wqs:
    print(f"\t{res['template_name']} (WQS): \t{str(res['response_time'])[:6]}")
  for res in qlever:
    print(f"\t{res['template_name']} (Qlever): \t{str(res['response_time'])[:6]}")
  
  print(f"Magnitudes on entity {entity}:")
  for res in wqs:
    try:
      res['results'] = res['response_content']['results']
      print(f"\t{res['template_name']} (WQS): \t{len(res['results'])}")
    except:
      raise RuntimeError(res['response_content']['exception'])
  for res in qlever:
    try:
      res['results'] = res['response_content']['results']
      print(f"\t{res['template_name']} (Qlever): \t{len(res['results'])}")
    except:
      raise RuntimeError(res['response_content']['exception'])

  all_results = wqs + qlever
  if len(all_results) != 2:
    return
  res_1, res_2 = all_results[0], all_results[1]
  res_1_name, res_2_name = res_1['template_name'], res_2['template_name']
  try:
    # drop color and label data for comparison
    if ignore_label:
      res_1 = [{k: v for k, v in row.items() if k != "rgb" and not k.endswith("Label")} for row in res_1["response_content"]["results"]]
      res_2 = [{k: v for k, v in row.items() if k != "rgb" and not k.endswith("Label")} for row in res_2["response_content"]["results"]]
    else:
      res_1 = [{k: v for k, v in row.items() if k!= "rgb"} for row in res_1["response_content"]["results"]]
      res_2 = [{k: v for k, v in row.items() if k!= "rgb"} for row in res_2["response_content"]["results"]]
  except:
    raise RuntimeError("Results don't include data. Probably connection or server issue. Please try again.")

  divergent_elements = list([str(elem) for elem in res_1 if elem not in res_2])
  if divergent_elements != []:
    print(f"Results from {res_1_name}, that were not returned from {res_2_name} for entity {wqs[0]['entity']}:", end="\n\t")
    print("\n\t".join(divergent_elements))
  divergent_elements = list([str(elem) for elem in res_2 if elem not in res_1])
  if divergent_elements != []:
    print(f"Results from {res_2_name}, that were not returned from {res_1_name} for entity {wqs[0]['entity']}:", end="\n\t")
    print("\n\t".join(divergent_elements))

def parse_cli_args():
  parser = argparse.ArgumentParser(description=
    'Compare SPARQL templates for Wikidata entities running on different backends. \
    Compares line by line results if 2 templates are given, otherwise it only compares runtimes and magnitudes of returned results')
  parser.add_argument('--qids', type=str, nargs='+', required=True, 
                      help='Qids of wikidata entities, that will be used to compare the queries')
  parser.add_argument('--print-query', action='store_true',
                      help='Prints the queries before executing them.')
  parser.add_argument('--ignore-label', action='store_true',
                      help='Ignores differences in the labels.')
  parser.add_argument('--qlever', type=str, nargs='+',
                      help='run these templates with qlever and compare them against all other templates (qlever- or wqs-run)')
  parser.add_argument('--wqs', type=str, nargs='+',
                      help='run these templates with wqs and compare them against all other templates (qlever- or wqs-run)')  
  return parser.parse_args()


if __name__ == "__main__":
  # cli parsing
  args = parse_cli_args()
  wikidata_entities = args.qids
  qlever_templates = args.qlever if args.qlever is not None else []
  wqs_templates = args.wqs if args.wqs is not None else []
  print_query = args.print_query
  ignore_label = args.ignore_label

  if len(qlever_templates) + len(wqs_templates) == 0:
    raise RuntimeError("No templates to compare provided. Add them with either --qlever or --wqs depending on how you want them to be run.")
  qlever_templates = list(read_sparql_templates(qlever_templates))
  wqs_templates = list(read_sparql_templates(wqs_templates))

  for wikidata_entity in wikidata_entities:
    print(f"Comparing {len(qlever_templates) + len(wqs_templates)} queries for Entity: {wikidata_entity}")

    wqs_results = []
    for i, (template_name, template) in enumerate(wqs_templates):
      print(f"Waiting on request {i+1} (WQS)  ...  ", end='\r')
      # get results of query from wqs api
      wqs_results.append(run_template(template_name, template, wikidata_entity, print_query=print_query, url=WQS_API_URL))
    
    qlever_results = []
    for i, (template_name, template) in enumerate(qlever_templates):
      print(f"Waiting on request {i+len(wqs_results)+1} (Qlever) ...     ", end='\r')
      # get results of query from qlever api
      qlever_results.append(run_template(template_name, template, wikidata_entity, print_query=print_query, url=QLEVER_API_URL))

    print_differences(wqs_results, qlever_results, ignore_label=ignore_label)
