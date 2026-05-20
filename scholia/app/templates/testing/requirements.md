The scripts in this directory run with python 3 and the following libraries (which don't come with the standard library):
- pandas
- jinja2
- requests
- sparqlwrapper

Or you can simply build the provided Dockerfile:
  docker build -t scholia-testing -f Dockerfile.testing .
And run it: 
  docker run -it --rm -v "$(pwd)/..":/templates scholia-testing
note: it is important for test_templates.py to have port forwarding so you can prompt the locally running qlever server and to be mounted directly on the repo to access the templates