# Signal Hierarchy Extractor

一个用于帮助 LLM 定位 RTL 具体信号的工具。

在复杂 RTL 项目中，目标信号可能隐藏在很深的模块例化关系里。直接让 LLM 或人工阅读大量源码去查找，容易出现效率低、路径漏查、模块名和例化名混淆等问题。本工具通过 Yosys 解析 Verilog/SystemVerilog，并从指定顶层模块开始遍历实例树，自动输出目标信号的完整层级路径，帮助 LLM 更准确地理解和使用 RTL 中的真实信号位置。

## 依赖

- Python 3.8+
- Yosys，需要能在命令行中直接执行 `yosys`

安装 Yosys 示例：

```bash
sudo apt-get install yosys
```

Python 不需要额外安装第三方库。

## 基本用法

在项目根目录下运行：

```bash
python3 src/signal_hierarchy_extractor.py \
  -i <RTL文件/RTL目录/filelist.f> \
  -t <顶层模块名> \
  -s <目标信号或模块名::目标信号> \
  -o <输出文件>
```

例如：

```bash
python3 src/signal_hierarchy_extractor.py \
  -i rtl \
  -t top_module \
  -s "sub_module::target_signal" \
  --incdir include \
  -o outputs/signal_paths.json
```

## 参数说明

| 参数 | 是否必填 | 说明 |
| --- | --- | --- |
| `-i`, `--input_rtl` | 是 | RTL 输入，可以是单个 `.v/.sv` 文件、RTL 目录，或 `.f` filelist。目录会递归扫描 `.v` 和 `.sv` 文件。 |
| `-t`, `--top` | 是 | 顶层模块名，脚本会从该模块开始向下遍历层级。 |
| `-s`, `--signal` | 是 | 目标信号。可以写 `signal_name`，也可以写 `module_name::signal_name` 进行精确匹配。 |
| `-o`, `--output` | 否 | 输出文件，默认是 `signal_paths.json`。后缀为 `.json` 时输出 JSON，否则输出纯文本。 |
| `--incdir` | 否 | Verilog include 目录，可重复传入多次。 |

## 路径说明

脚本支持相对路径：

- `-i rtl` 会按当前运行命令的目录查找 `rtl/`
- `--incdir include` 会按当前运行命令的目录查找 `include/`
- `-o outputs/result.json` 会输出到当前运行命令目录下的 `outputs/`
- `.f` filelist 内部的相对文件路径和 `+incdir+` 路径，会按该 `.f` 文件所在目录解析

## 输出格式

JSON 输出示例：

```json
{
    "top_module": "top_module",
    "target": "sub_module::target_signal",
    "found_chains": [
        "top_module.u_sub_module.target_signal"
    ]
}
```

纯文本输出示例：

```text
top_module.u_sub_module.target_signal
```

## 常见问题

如果提示找不到 Yosys：

```text
[Error] Yosys executable not found.
```

请确认已经安装 Yosys，并且 `yosys` 在 `PATH` 中。

如果找不到预期信号，优先检查：

- `-t` 顶层模块名是否正确
- `--incdir` 是否包含所有需要的 include 目录
- 目标信号是否应该使用 `module_name::signal_name` 形式精确匹配
