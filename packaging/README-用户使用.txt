scanspy Windows x64 使用说明
更新日期：2026-09-10

本次更新：混合扫描件 MIXED_SCANNED 的 scanned 改为 false。
纯扫描件 SCANNED 仍返回 true，普通 PDF STANDARD 返回 false。
type、页数统计和 JSON 字段结构保持不变。

一、运行要求
  - Windows 10 / Windows 11 64 位环境。
  - scanspy.exe 是命令行程序，用户不需要安装 Python 或项目依赖。
  - 请在 PowerShell 或 CMD 中运行；直接双击不会弹出文件选择窗口。

二、PowerShell 运行方式
  & "C:\tools\scanspy\scanspy.exe" "C:\input\file.pdf"
  & "C:\tools\scanspy\scanspy.exe" "https://example.com/file.pdf"
  & "C:\tools\scanspy\scanspy.exe" "C:\input\a.pdf" "C:\input\b.pdf"

  如果当前目录就是 EXE 所在目录，也可以运行：
  .\scanspy.exe "C:\input\file.pdf"

  CMD 中运行时，去掉开头的 &：
  "C:\tools\scanspy\scanspy.exe" "C:\input\file.pdf"

三、业务判断规则
  STANDARD       普通 PDF       scanned=false
  MIXED_SCANNED  混合扫描件      scanned=false
  SCANNED        纯扫描件        scanned=true

  混合扫描件示例（仅列出部分结果字段）：
  {"scanned":false,"type":"MIXED_SCANNED","pageCount":2,"scannedPages":1,"textPages":1}

  请先确认 code=200、success=true，再读取 scanned。
  处理失败时 type=UNKNOWN、scanned=false，不能将处理失败当作检测通过。
  批量调用时，data 中每个文件都有独立的 code 和 success。

四、输入与输出
  - 支持本地 .pdf 文件和 URL 路径以 .pdf 结尾的 HTTP/HTTPS PDF 直链。
  - 不支持把 DOCX、网页预览地址或非 PDF 下载内容直接作为输入。
  - URL 文件下载到 %TMP% / %TEMP% 下的 scanspy-* 临时目录，处理结束后自动清理。
  - 标准输出是一行 UTF-8 编码的 JSON，外层为 code、success、data、msg、errorCode。
  - data 始终是数组，每个输入对应一个结果，顺序与输入顺序一致。
  - 全部处理成功时进程退出码为 0；参数错误或有文件处理失败时为 1。
    退出码表示是否完成处理，不表示文件是否为扫描件。

五、页数统计与检测范围
  - pageCount：PDF 实际总页数。
  - scannedPages：当前结构规则识别到的扫描页数。
  - textPages：能提取到文字的页数，可能包含仅有页眉、页脚或页码的页面。
  - 同一页可以同时计入 scannedPages 和 textPages，两者不能直接相加作为总页数。
  - confidence 固定为 0.0，不是“检测失败”或“零可信度”的含义。
  - scanned=false 不代表完全没有扫描图片，也不代表全文不需要 OCR。
  - 本工具进行 PDF 结构检测，不执行 OCR，也不判断附件是否满足投标要求。

六、替换与验证
  - 将本次交付的 scanspy.exe 放到业务系统实际调用的路径，保留原有调用参数。
  - 如果提示文件被占用，待正在执行的检测进程结束后再替换。
  - 用已知混合扫描件复测，应得到 type=MIXED_SCANNED、scanned=false。
  - 再用纯扫描件复测，应得到 type=SCANNED、scanned=true。
  - 详细字段、错误码和调用示例见同目录 scanspy-详细使用文档.pdf。
