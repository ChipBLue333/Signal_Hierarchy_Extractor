#!/usr/bin/env python3

import os
import sys
import json
import argparse
import subprocess
import glob


def parse_arguments():
    parser = argparse.ArgumentParser(description="Extract RTL signal hierarchy paths for LLM-assisted analysis")
    parser.add_argument('-i', '--input_rtl', required=True, help="Input RTL file (.v/.sv), folder path, or filelist (.f)")
    parser.add_argument('-t', '--top', required=True, help="Top module name")
    parser.add_argument('-s', '--signal', required=True, help="Target signal. Format: 'signal_name' or 'module_name::signal_name'")
    parser.add_argument('-o', '--output', default='signal_paths.json', help="Output file path (default: signal_paths.json)")
    parser.add_argument('--incdir', action='append', default=[], help="Include directory for verilog parsing. Can be used multiple times.")
    return parser.parse_args()


def yosys_quote(path):
    """Quote a path for use inside a Yosys script."""
    return '"' + path.replace('\\', '\\\\').replace('"', '\\"') + '"'


def run_yosys(input_rtl, top_module, incdirs):
    """Generate and run Yosys script to parse RTL into JSON netlist."""
    temp_json = ".temp_hierarchy.json"
    temp_ys = ".temp_script.ys"
    
    # 1. Collect RTL files
    v_files = []
    if os.path.isfile(input_rtl):
        if input_rtl.endswith('.f'):
            # Simple parse filelist
            filelist_dir = os.path.dirname(os.path.abspath(input_rtl))
            with open(input_rtl, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('//') and not line.startswith('#'):
                        if line.startswith('+incdir+'):
                            incdir = line.replace('+incdir+', '', 1)
                            if not os.path.isabs(incdir):
                                incdir = os.path.join(filelist_dir, incdir)
                            incdirs.append(incdir)
                        else:
                            if not os.path.isabs(line):
                                line = os.path.join(filelist_dir, line)
                            v_files.append(line)
        else:
            v_files.append(input_rtl)
    elif os.path.isdir(input_rtl):
        v_files.extend(glob.glob(os.path.join(input_rtl, '**', '*.v'), recursive=True))
        v_files.extend(glob.glob(os.path.join(input_rtl, '**', '*.sv'), recursive=True))
    else:
        print(f"[Error] Input {input_rtl} is neither a valid file nor directory.")
        sys.exit(1)

    if not v_files:
        print(f"[Error] No Verilog/SystemVerilog files found from input: {input_rtl}")
        sys.exit(1)

    # 2. Build Yosys script
    ys_commands = []
    for inc in incdirs:
        ys_commands.append(f"verilog_defaults -add -I{yosys_quote(inc)}")
    
    for vf in v_files:
        ys_commands.append(f"read_verilog -sv {yosys_quote(vf)}")
    
    ys_commands.append(f"hierarchy -check -top {top_module}")
    ys_commands.append("proc")
    ys_commands.append("prep")
    ys_commands.append(f"write_json {yosys_quote(temp_json)}")
    
    with open(temp_ys, 'w') as f:
        f.write("\n".join(ys_commands) + "\n")
    
    # 3. Execute Yosys
    print("[Info] Running Yosys parsing...")
    try:
        result = subprocess.run(['yosys', '-q', temp_ys], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0 or not os.path.exists(temp_json):
            print("[Error] Yosys failed to parse the RTL:")
            print(result.stderr)
            sys.exit(1)
    except FileNotFoundError:
        print("[Error] Yosys executable not found. Please ensure yosys is installed and in your PATH.")
        sys.exit(1)
        
    return temp_json, temp_ys


def clean_name(name):
    """Clean yosys prefix escapes from names (e.g. \\module_name -> module_name)"""
    return name.lstrip('\\')


def base_module_name(module_name):
    """Return the original RTL module name from a Yosys module key."""
    stripped = clean_name(module_name)
    if not stripped.startswith('$paramod'):
        return stripped

    parts = stripped.split('\\')
    if len(parts) >= 2:
        return parts[1]
    return stripped


def find_target_chains(json_path, top_module, target_signal):
    """DFS traversal of module hierarchy to find target signal chain."""
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    modules = data.get('modules', {})
    
    # Module names might have mapping
    mod_map = {clean_name(k): k for k in modules.keys()}
    
    if top_module not in mod_map:
        print(f"[Error] Top module '{top_module}' not found in the parsed design.")
        return []

    target_mod = None
    target_sig = target_signal
    if '::' in target_signal:
        target_mod, target_sig = target_signal.split('::', 1)
    elif ':' in target_signal:
        target_mod, target_sig = target_signal.split(':', 1)

    found_chains = []
    visited_insts = set() # Avoid combinational loops or recursive includes if any

    def dfs(current_mod_key, current_chain):
        mod_data = modules.get(current_mod_key, {})
        
        # 1. Check if the target signal exists in this module's nets
        netnames = mod_data.get('netnames', {})
        cleaned_nets = [clean_name(net) for net in netnames.keys()]
        
        # If target module is defined, we must check if we are in the target module
        # Need to handle Yosys paramod prefixes for module matching.
        # Yosys generates names like '$paramod\sirv_gnrl_dfflrs\WIDTH=32'1' or '$paramod$43789d\sirv_sim_ram'
        base_mod = base_module_name(current_mod_key)
        is_target_module_match = (target_mod is None) or (base_mod == target_mod)
        
        if is_target_module_match and (target_sig in cleaned_nets):
            found_chains.append(".".join(current_chain) + "." + target_sig)
            
        # 2. Recurse into instances (cells)
        cells = mod_data.get('cells', {})
        for inst_name, inst_data in cells.items():
            cleaned_inst = clean_name(inst_name)
            sub_mod_name = inst_data.get('type')
            
            # Avoid Yosys internal primitive cells starting with '$' but allow parameterized modules
            if sub_mod_name and (not sub_mod_name.startswith('$') or sub_mod_name.startswith('$paramod')):
                inst_path_id = tuple(current_chain + [cleaned_inst])
                if inst_path_id not in visited_insts:
                    visited_insts.add(inst_path_id)
                    dfs(sub_mod_name, current_chain + [cleaned_inst])

    # Start DFS
    # Note: Using top_module as the root of the path chain
    dfs(mod_map[top_module], [top_module])
    
    return found_chains


def write_results(output_path, result):
    output_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(output_dir, exist_ok=True)

    if output_path.endswith('.json'):
        with open(output_path, 'w') as f:
            json.dump(result, f, indent=4)
        print(f"\n[Info] Results exported to JSON: {output_path}")
    else:
        with open(output_path, 'w') as f:
            for chain in result["found_chains"]:
                f.write(chain + "\n")
        print(f"\n[Info] Results exported to TXT: {output_path}")


def main():
    args = parse_arguments()
    
    print("=" * 60)
    print(" Signal Hierarchy Extractor")
    print("=" * 60)
    
    temp_json, temp_ys = run_yosys(args.input_rtl, args.top, args.incdir)
    try:
        print("[Info] Parsing Hierarchy Tree...")
        chains = find_target_chains(temp_json, args.top, args.signal)

        print("\n--- Extraction Results ---")
        if not chains:
            print(f"[-] No instantiation chain found for: {args.signal}")
        else:
            for idx, chain in enumerate(chains):
                print(f"[{idx+1}] {chain}")

        out_dict = {
            "top_module": args.top,
            "target": args.signal,
            "found_chains": chains
        }
        write_results(args.output, out_dict)
    finally:
        for temp_file in (temp_json, temp_ys):
            if os.path.exists(temp_file):
                os.remove(temp_file)


if __name__ == "__main__":
    main()
