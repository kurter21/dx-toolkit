#!/usr/bin/env python2.7
#
# Copyright (C) 2013-2016 DNAnexus, Inc.
#
# This file is part of dx-toolkit (DNAnexus platform client libraries).
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may not
#   use this file except in compliance with the License. You may obtain a copy
#   of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import sys, json, re

preamble = '''# Do not modify this file by hand.
#
# It is automatically generated by src/api_wrappers/generateRubyAPIWrappers.py.
# (Run make api_wrappers to update it.)

require 'dxruby'

module DX
  module API'''

postscript = '''  end
end'''

class_method_template = '''    # Invokes the {route} API method.{docs_ref}
    def self.{wrapper_method_name}(input_params={{}}, opts={{}})
      opts = {{ "always_retry" => {retry} }}.merge(opts)
      return DX::http_request("{route}", input_params, opts)
    end
'''

object_method_template = '''    # Invokes the {route} API method.{docs_ref}
    def self.{wrapper_method_name}(object_id, input_params={{}}, opts={{}})
      opts = {{ "always_retry" => {retry} }}.merge(opts)
      return DX::http_request("/#{{object_id}}/{api_method_name}", input_params, opts)
    end
'''

app_object_method_template = '''    # Invokes the /app-xxxx/{api_method_name} API method.{docs_ref}
    def self.{wrapper_method_name}(app_name_or_id, app_alias=nil, input_params={{}}, opts={{}})
      opts = {{ "always_retry" => {retry} }}.merge(opts)
      fully_qualified_version = app_name_or_id + (app_alias ? ('/' + app_alias) : '')
      return DX::http_request("/#{{fully_qualified_version}}/{api_method_name}", input_params, opts)
    end
'''

def make_docs_ref(url):
    return ("\n    #\n    # For more info, see: " + url) if url else ""

def make_class_method(wrapper_method_name, route, retry=False, url=None):
    return class_method_template.format(wrapper_method_name=wrapper_method_name, route=route, retry=retry, docs_ref=make_docs_ref(url))

def make_object_method(wrapper_method_name, api_method_name, route, retry=False, url=None):
    return object_method_template.format(wrapper_method_name=wrapper_method_name, api_method_name=api_method_name, route=route, retry=retry, docs_ref=make_docs_ref(url))

def make_app_object_method(wrapper_method_name, api_method_name, retry=False, url=None):
    return app_object_method_template.format(wrapper_method_name=wrapper_method_name, api_method_name=api_method_name, retry=retry, docs_ref=make_docs_ref(url))

# This function converts a "camelCase" string to underscore version, e.g: "camel_case"
def camel_case_to_underscore(name):
    return re.sub("[A-Z]+", lambda m: "_" + m.group(0).lower(), name, 0)

print preamble

for method in json.loads(sys.stdin.read()):
    route, signature, opts = method
    wrapper_method_name = camel_case_to_underscore(signature.split("(")[0])
    retry = "true" if (opts['retryable']) else "false"
    if (opts['objectMethod']):
        root, oid_route, api_method_name = route.split("/")
        if oid_route == 'app-xxxx':
            print make_app_object_method(wrapper_method_name, api_method_name, retry=retry, url=opts.get('docsLink', None))
        else:
            print make_object_method(wrapper_method_name, api_method_name, route, retry=retry, url=opts.get('docsLink', None))
    else:
        print make_class_method(wrapper_method_name, route, retry=retry, url=opts.get('docsLink', None))

print postscript
