sealcheck Windows x64 使用说明

功能：
  判断 PDF 中是否存在签章。只要 PDF 里存在至少 1 个签章字段、签章控件或签名对象，就返回 hasSignature=true。

运行方式：
  C:\path\to\sealcheck.exe "C:\path\to\file.pdf"
  C:\path\to\sealcheck.exe "C:\path\to\a.pdf" "C:\path\to\b.pdf"
  C:\path\to\sealcheck.exe "https://example.com/file.pdf"

返回重点：
  hasSignature=true   表示检测到至少 1 个签章标记
  hasSignature=false  表示没有检测到签章标记

说明：
  - sealcheck.exe 是独立 CLI，不和 scanspy.exe 打包在一起。
  - 只支持 .pdf 本地文件和 .pdf 直链 URL。
  - URL 必须是 http/https，并且路径以 .pdf 结尾。
  - URL 会下载到系统临时目录，检测完成后自动删除。
  - 本工具只判断有没有签章，不校验证书、不判断是否篡改、不返回签章页码明细。