import os
from pathlib import Path
from SCons.Script.SConscript import SConsEnvironment
from SCons.Node import Node
import random

LLVM_LINK = "llvm-link"
LLC = "llc"
OPT = "opt"

def wrap_builder(builder, handler):
    class ProxyObject(object):
        def __call__(self, *args, **kwargs):
            #print('Hi Jack!', args, kwargs)
            return handler(*args, **kwargs)
        def __getattr__(self, name):
            return getattr(builder, name)
    return ProxyObject()


def get_name_str(src):
    if type(src) is list:
        return get_name_str(src[0])
    elif type(src) is str:
        if(src.startswith("[")):
            return get_name_str(eval(src)) 
        return src
    else:
        return get_name_str(str(src))


def build_real_objects(_env, name, sources, llc_arg=""):
    name = name if type(name) is str else name[0]
    src_codes = []
    src_bcs = []
    src_objs = []

    # seperate uncompiled codes and object files that generate by other builders
    for i in range(len(sources)): 
        src_name = get_name_str(sources[i])
        print("---", src_name)
        if src_name.endswith(tuple( _env["CPPSUFFIXES"] )):
            src_codes.append(sources[i])
        elif src_name.endswith(".bc"):
            src_bcs.append(sources[i])
        else:
            src_objs.append(sources[i])
    if len(src_codes) == 0 and len(src_bcs) == 0:
        return src_objs
    
    lib_bcs = [*filter(lambda i: get_name_str(i).endswith(".bc"), _env["LIBS"])]
    print("----", [str(i) for i in src_bcs])
    # then build the uncompiled codes to one object
    name_suffix = ""
    if len(src_codes) == 1:
        name_suffix = ".from." + Path(get_name_str(src_codes[0])).stem
    obj_from_code_name = name + name_suffix
    print(obj_from_code_name)
    obj_from_code_bc = _env.Library(obj_from_code_name + ".bc", src_codes + src_bcs + lib_bcs)
    obj_from_code = _env.Command(
        obj_from_code_name + ".o", 
        obj_from_code_bc, 
        f"{LLC} -filetype=obj {llc_arg} -o $TARGET $SOURCES"
    )
    return src_objs + obj_from_code


def process_static_libs(_env):
    libs = _env['LIBS']
    for i in range(len(libs)):
        name = get_name_str(libs[i])
        if name.endswith('.bc'):
            lib = build_real_objects(_env, name[0:-3], libs[i])    
            libs[i] = lib


def hijack_builders(env: "SConsEnvironment"):
    org_object = env['BUILDERS']['Object']
    org_library = env['BUILDERS']['Library']
    org_shlibrary = env['BUILDERS']['SharedLibrary']
    org_program = env['BUILDERS']['Program']

    """
        builder(env: SConsEnvironment, name: string[], sources: Node[]?[])
    """
    def object_handler(*args, **kwargs):
        (_env, name, sources) = args
        # it appears that some script will try to define OBJSUFFIX as well
        # if we just overwrite it will cause output duplicated error
        org_suffix = _env["OBJSUFFIX"]
        _env["OBJSUFFIX"] = org_suffix + '.bc'
        ccflags = _env["CCFLAGS"] + ["-emit-llvm"]
        ret = org_object(*args, CCFLAGS=ccflags, **kwargs)
        _env["OBJSUFFIX"] = org_suffix
        return ret

    def library_handler(*args, **kwargs):
        (_env, name, sources) = args
        print(f"LIBRARY: {name}")
        for i in range(len(sources)):
            src_name = str(sources[i] if type(sources[i]) is not list else sources[i][0])
            if src_name.endswith(tuple( _env["CPPSUFFIXES"] )):
                # try to build library without bitcode file, build it first
                sources[i] = [ _env.Object(src_name) ]
        #print([str(i) for i in sources])
        target_name = name if type(name) is str else name[0] + _env['LIBSUFFIX'] + '.bc'
        return _env.Command(target_name, sources, f"{LLVM_LINK} -o $TARGET $SOURCES")

    def shlibrary_handler(*args, **kwargs):
        (_env, name, sources) = args
        objs = build_real_objects(
            _env, name, sources,
            "--relocation-model=pic"
        )
        #process_static_libs(_env)
        return org_shlibrary(_env, name, objs, **kwargs)

    def program_handler(*args, **kwargs):
        (_env, name, sources) = args
        #print([str(i) for i in _env["LIBS"]])
        print([str(i) for i in sources])
        objs = build_real_objects(_env, name, sources, "")
        
        #process_static_libs(_env)
        new_env = _env.Clone()
        new_env["LIBS"] = [*filter(lambda i: not get_name_str(i).endswith(".bc"), new_env["LIBS"])]
        new_env.Append(LINKFLAGS='-fuse-ld=lld')
        new_env.Append(LINKFLAGS='-Wl,--gc-sections')
        new_env.Append(LINKFLAGS='-Wl,-allow-multiple-definition')
        new_env.Append(LIBS="stdc++")
        ret = org_program(new_env, name, objs, **kwargs)
        return ret

    env['BUILDERS']['Object'] = wrap_builder(org_object, object_handler)
    env['BUILDERS']['Library'] = wrap_builder(org_library, library_handler)
    env['BUILDERS']['SharedLibrary'] = wrap_builder(org_shlibrary, shlibrary_handler)
    env['BUILDERS']['Program'] = wrap_builder(org_program, program_handler)