The scripts in this directory run with python 3 and the following libraries (which don't come with the standard library):
- pandas
- jinja2
- requests
- sparqlwrapper

Or you can simply build the provided Dockerfile like this:
  docker build -t scholia-testing -f Dockerfile.testing .
And run it like this: 
  docker run -it --rm -v "$(pwd)/..":/templates scholia-testing
note: it is important for test_templates.py to have port forwarding and to be mounted directly on the repo, so you can prompt the locally running qlever server and acces the templates respectively