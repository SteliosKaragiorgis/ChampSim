#    Copyright 2023 The ChampSim Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import difflib
import hashlib
import itertools
import operator
import os
import json
import contextlib

from . import makefile
from . import instantiation_file
from . import constants_file
from . import modules
from . import util

constants_file_name = 'champsim_constants.h'
instantiation_file_name = 'core_inst.inc'
core_module_declaration_file_name = 'ooo_cpu_module_decl.inc'
core_module_definition_file_name = 'ooo_cpu_module_def.inc'
cache_module_declaration_file_name = 'cache_module_decl.inc'
cache_module_definition_file_name = 'cache_module_def.inc'
makefile_file_name = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '_configuration.mk')

cxx_generated_warning = ('/***', ' * THIS FILE IS AUTOMATICALLY GENERATED', ' * Do not edit this file. It will be overwritten when the configure script is run.', ' ***/', '')
make_generated_warning = ('###', '# THIS FILE IS AUTOMATICALLY GENERATED', '# Do not edit this file. It will be overwritten when the configure script is run.', '###', '')

def files_are_different(rfp, new_rfp):
    old_file_lines = list(l.strip() for l in rfp)
    new_file_lines = list(l.strip() for l in new_rfp)
    return difflib.SequenceMatcher(a=old_file_lines, b=new_file_lines).ratio() < 1

def write_if_different(fname, new_file_string):
    should_write = True
    if os.path.exists(fname):
        with open(fname, 'rt') as rfp:
            should_write = files_are_different(rfp, new_file_string.splitlines())

    if should_write:
        with open(fname, 'wt') as wfp:
            wfp.write(new_file_string)

def get_map_lines(fname_map):
    yield from ('#define {} {}'.format(*x) for x in fname_map.items())

class FileWriter:
    def __init__(self, bindir_name=None, objdir_name=None):
        champsim_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        core_sources = os.path.join(champsim_root, 'src')

        self.fileparts = []
        self.bindir_name = bindir_name
        self.core_sources = core_sources
        self.objdir_name = objdir_name

    def write_files(self, parsed_config, bindir_name=None, srcdir_names=None, objdir_name=None):
        local_bindir_name = bindir_name or self.bindir_name
        local_srcdir_names = (*(srcdir_names or []), self.core_sources)
        local_objdir_name = objdir_name or self.objdir_name

        build_id = hashlib.shake_128(json.dumps(parsed_config).encode('utf-8')).hexdigest(4)

        inc_dir = os.path.join(os.path.abspath(local_objdir_name), build_id, 'inc')

        executable, elements, modules_to_compile, module_info, config_file, env = parsed_config

        self.fileparts.append((os.path.join(inc_dir, instantiation_file_name), instantiation_file.get_instantiation_lines(**elements))) # Instantiation file
        self.fileparts.append((os.path.join(inc_dir, constants_file_name), constants_file.get_constants_file(config_file, elements['pmem']))) # Constants header

        # Core modules file
        core_declarations, core_definitions = modules.get_ooo_cpu_module_lines(module_info['indirect_branch'], module_info['branch'], module_info['btb'])

        self.fileparts.extend((
            (os.path.join(inc_dir, core_module_declaration_file_name), core_declarations),
            (os.path.join(inc_dir, core_module_definition_file_name), core_definitions)
        ))

        # Cache modules file
        cache_declarations, cache_definitions = modules.get_cache_module_lines(module_info['pref'], module_info['repl'])

        self.fileparts.extend((
            (os.path.join(inc_dir, cache_module_declaration_file_name), cache_declarations),
            (os.path.join(inc_dir, cache_module_definition_file_name), cache_definitions)
        ))

        joined_module_info = util.subdict(util.chain(*module_info.values()), modules_to_compile) # remove module type tag
        self.fileparts.extend((os.path.join(inc_dir, m['name'] + '.inc'), get_map_lines(util.chain(m['func_map'], m.get('deprecated_func_map', {})))) for m in joined_module_info.values())
        self.fileparts.append((makefile_file_name, makefile.get_makefile_lines(local_objdir_name, build_id, os.path.normpath(os.path.join(local_bindir_name, executable)), local_srcdir_names, joined_module_info, env)))

    def finish(self):
        for fname, fcontents in itertools.groupby(sorted(self.fileparts, key=operator.itemgetter(0)), key=operator.itemgetter(0)):
            os.makedirs(os.path.abspath(os.path.dirname(fname)), exist_ok=True)
            if os.path.splitext(fname)[1] in ('.cc', '.h', '.inc'):
                contents_with_header = itertools.chain(cxx_generated_warning, *(f[1] for f in fcontents))
            elif os.path.splitext(fname)[1] in ('.mk',):
                contents_with_header = itertools.chain(make_generated_warning, *(f[1] for f in fcontents))
            else:
                contents_with_header = itertools.chain.from_iterable(f[1] for f in fcontents) # no header

            write_if_different(fname, '\n'.join(contents_with_header))


@contextlib.contextmanager
def writer(bindir_name=None, objdir_name=None):
    w = FileWriter(bindir_name, objdir_name)
    try:
        yield w
    finally:
        w.finish()
