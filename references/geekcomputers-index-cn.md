# geekcomputers/Python 中文分类索引

> 一个拥有 **35.1k Stars** 的实用 Python 脚本合集仓库，面向初学者和日常自动化需求。
> 
> 仓库地址：https://github.com/geekcomputers/Python
>
> 本项目汇集了数百个可直接运行的 Python 脚本和小型项目，涵盖文件管理、网络工具、游戏开发、机器学习、GUI 应用等多个领域，非常适合 Python 初学者学习参考，也适合开发者快速找到满足日常自动化需求的现成脚本。

---

## 快速导航

- [文件与系统管理](#文件与系统管理)
- [网络与下载](#网络与下载)
- [媒体与文档处理](#媒体与文档处理)
- [信息获取与爬虫](#信息获取与爬虫)
- [游戏娱乐](#游戏娱乐)
- [GUI 应用与工具](#gui-应用与工具)
- [安全与加密](#安全与加密)
- [机器学习与 AI](#机器学习与-ai)
- [算法与数据结构](#算法与数据结构)
- [数学与工具](#数学与工具)
- [社交与通信](#社交与通信)
- [其他实用脚本](#其他实用脚本)

---

## 文件与系统管理

文件操作、目录管理、系统信息、日志处理等日常系统管理脚本。

- [batch_file_rename.py](https://github.com/geekcomputers/Python/blob/master/batch_file_rename.py) — 批量重命名文件，支持修改扩展名
- [create_dir_if_not_there.py](https://github.com/geekcomputers/Python/blob/master/create_dir_if_not_there.py) — 检查 home 目录下指定目录是否存在，不存在则自动创建
- [dir_test.py](https://github.com/geekcomputers/Python/blob/master/dir_test.py) — 测试 `testdir` 目录是否存在，不存在则创建
- [fileinfo.py](https://github.com/geekcomputers/Python/blob/master/fileinfo.py) — 显示指定文件的详细信息
- [folder_size.py](https://github.com/geekcomputers/Python/blob/master/folder_size.py) — 扫描当前目录及所有子目录，显示各目录大小
- [logs.py](https://github.com/geekcomputers/Python/blob/master/logs.py) — 搜索 `*.log` 文件并压缩，添加日期戳
- [move_files_over_x_days.py](https://github.com/geekcomputers/Python/blob/master/move_files_over_x_days.py) — 将超过指定天数的文件从源目录移动到目标目录
- [puttylogs.py](https://github.com/geekcomputers/Python/blob/master/puttylogs.py) — 压缩指定目录中的日志文件
- [script_count.py](https://github.com/geekcomputers/Python/blob/master/script_count.py) — 扫描脚本目录并统计各类脚本的数量
- [script_listing.py](https://github.com/geekcomputers/Python/blob/master/script_listing.py) — 列出指定目录及子目录中的所有文件
- [testlines.py](https://github.com/geekcomputers/Python/blob/master/testlines.py) — 打开文件并打印指定行开始的 100 行内容
- [changemac.py](https://github.com/geekcomputers/Python/blob/master/changemac.py) — 在 Linux 系统上修改或随机生成 MAC 地址
- [osinfo.py](https://github.com/geekcomputers/Python/blob/master/osinfo.py) — 显示操作系统详细信息
- [smart_file_organizer.py](https://github.com/geekcomputers/Python/blob/master/smart_file_organizer.py) — 按文件类型自动整理目录中的文件
- [1 File handle](https://github.com/geekcomputers/Python/tree/master/1%20File%20handle) — 文件操作相关脚本合集
- [file_handle](https://github.com/geekcomputers/Python/tree/master/file_handle) — 文件处理相关脚本
- [Downloaded Files Organizer](https://github.com/geekcomputers/Python/tree/master/Downloaded%20Files%20Organizer) — 下载文件自动整理器
- [Cat](https://github.com/geekcomputers/Python/tree/master/Cat) — Linux `cat` 命令的 Python 实现
- [XML](https://github.com/geekcomputers/Python/tree/master/XML) — XML 文件处理工具
- [depreciated_programs](https://github.com/geekcomputers/Python/tree/master/depreciated_programs) — 已弃用但仍可参考的旧脚本
- [dialogs](https://github.com/geekcomputers/Python/tree/master/dialogs) — 各类对话框实现
- [img](https://github.com/geekcomputers/Python/tree/master/img) — 图片相关工具脚本

---

## 网络与下载

网络诊断、服务器管理、批量下载、YouTube 工具等网络相关脚本。

- [ping_servers.py](https://github.com/geekcomputers/Python/blob/master/ping_servers.py) — Ping 指定应用组关联的服务器
- [ping_subnet.py](https://github.com/geekcomputers/Python/blob/master/ping_subnet.py) — 扫描指定 IP 子网末段的可用地址
- [nslookup_check.py](https://github.com/geekcomputers/Python/blob/master/nslookup_check.py) — 读取 `server_list.txt` 对每个服务器执行 nslookup 查询
- [powerdown_startup.py](https://github.com/geekcomputers/Python/blob/master/powerdown_startup.py) — Ping 服务器列表中的机器，在线则加载 PuTTY 会话
- [site_health.py](https://github.com/geekcomputers/Python/blob/master/site_health.py) — 检查远程服务器健康状态
- [serial_scanner.py](https://github.com/geekcomputers/Python/blob/master/serial_scanner.py) — 列出 Linux/Windows 系统上可用的串口
- [get_youtube_view.py](https://github.com/geekcomputers/Python/blob/master/get_youtube_view.py) — 增加 YouTube 视频播放量/循环播放
- [youtube.py](https://github.com/geekcomputers/Python/blob/master/youtube.py) — 输入歌曲名获取最佳匹配的 YouTube URL 并播放
  - [CliYoutubeDownloader](https://github.com/geekcomputers/Python/tree/master/CliYoutubeDownloader) — CLI 版 YouTube 视频下载器
- [Youtube Downloader With GUI](https://github.com/geekcomputers/Python/tree/master/Youtube%20Downloader%20With%20GUI) — 带图形界面的 YouTube 下载器
- [Google_Image_Downloader](https://github.com/geekcomputers/Python/tree/master/Google_Image_Downloader) — Google 图片批量下载器
- [ImageDownloader](https://github.com/geekcomputers/Python/tree/master/ImageDownloader) — 通用图片下载工具
- [async_downloader](https://github.com/geekcomputers/Python/tree/master/async_downloader) — 异步批量下载器
- [Webbrowser](https://github.com/geekcomputers/Python/tree/master/Webbrowser) — 网页浏览器相关脚本

---

## 媒体与文档处理

PDF 转换、图片处理、视频缩略图提取、HTML 转换等媒体与文档处理脚本。

- [HTML_to_PDF](https://github.com/geekcomputers/Python/tree/master/HTML_to_PDF) — 将 HTML 页面转换为 PDF 文件
- [image2pdf](https://github.com/geekcomputers/Python/tree/master/image2pdf) — 将图片转换为 PDF 文件
- [Image-watermarker](https://github.com/geekcomputers/Python/tree/master/Image-watermarker) — 为图片添加水印
- [ExtractThumbnailFromVideo](https://github.com/geekcomputers/Python/tree/master/ExtractThumbnailFromVideo) — 从视频中提取缩略图
- [Turn your PDFs into audio books](https://github.com/geekcomputers/Python/tree/master/Turn%20your%20PDFs%20into%20audio%20books) — 将 PDF 转换为有声书
- [Extract-Table-from-pdf-txt-docx](https://github.com/geekcomputers/Python/tree/master/Extract-Table-from-pdf-txt-docx) — 从 PDF/TXT/DOCX 文件中提取表格
- [PDF](https://github.com/geekcomputers/Python/tree/master/PDF) — PDF 处理相关脚本合集
- [insta_image_saving](https://github.com/geekcomputers/Python/tree/master/insta_image_saving) — Instagram 图片保存工具
- [Colors](https://github.com/geekcomputers/Python/tree/master/Colors) — 颜色处理工具
- [Compression_Analysis](https://github.com/geekcomputers/Python/tree/master/Compression_Analysis) — 压缩算法分析工具

---

## 信息获取与爬虫

新闻获取、天气查询、维基百科、搜索引擎、浏览器历史等信息获取脚本。

- [Google_News.py](https://github.com/geekcomputers/Python/blob/master/Google_News.py) — 使用 BeautifulSoup 获取 Google 最新新闻标题和链接
- [Cricket_score.py](https://github.com/geekcomputers/Python/blob/master/Cricket_score.py) — 使用 BeautifulSoup 获取板球实时比分
- [News_App](https://github.com/geekcomputers/Python/tree/master/News_App) — 新闻应用，聚合展示新闻
- [Weather Scrapper](https://github.com/geekcomputers/Python/tree/master/Weather%20Scrapper) — 天气信息爬虫
- [Wikipdedia](https://github.com/geekcomputers/Python/tree/master/Wikipdedia) — Wikipedia 工具，词条查询等
- [Search_Engine](https://github.com/geekcomputers/Python/tree/master/Search_Engine) — 简易搜索引擎实现
- [BrowserHistory](https://github.com/geekcomputers/Python/tree/master/BrowserHistory) — 浏览器历史记录查看工具
- [JustDialScrapperGUI](https://github.com/geekcomputers/Python/tree/master/JustDialScrapperGUI) — JustDial 网站爬虫 GUI 工具
- [Translator](https://github.com/geekcomputers/Python/tree/master/Translator) — 翻译工具
- [insta_monitering](https://github.com/geekcomputers/Python/tree/master/insta_monitering) — Instagram 监控工具
- [Word_Dictionary](https://github.com/geekcomputers/Python/tree/master/Word_Dictionary) — 单词词典
- [email id dictionary](https://github.com/geekcomputers/Python/tree/master/email%20id%20dictionary) — 邮箱 ID 词典
- [Emoji Dictionary](https://github.com/geekcomputers/Python/tree/master/Emoji%20Dictionary) — 表情符号词典
- [NumberToNumberName](https://github.com/geekcomputers/Python/tree/master/NumberToNumberName) — 数字转中文/英文名称

---

## 游戏娱乐

各类经典游戏和小游戏的 Python 实现，涵盖街机、棋盘、猜谜等类型。

- [BlackJack_game](https://github.com/geekcomputers/Python/tree/master/BlackJack_game) — 21 点（BlackJack）赌场游戏
- [Checker_game_by_dz](https://github.com/geekcomputers/Python/tree/master/Checker_game_by_dz) — 跳棋游戏
- [Flappy Bird - created with tkinter](https://github.com/geekcomputers/Python/tree/master/Flappy%20Bird%20-%20created%20with%20tkinter) — 使用 tkinter 实现的 Flappy Bird 游戏
- [flappyBird_pygame](https://github.com/geekcomputers/Python/tree/master/flappyBird_pygame) — 使用 pygame 实现的 Flappy Bird 游戏
- [Snake Game Using Turtle](https://github.com/geekcomputers/Python/tree/master/Snake%20Game%20Using%20Turtle) — 使用 Turtle 图形库实现的贪吃蛇游戏
- [Snake_water_gun](https://github.com/geekcomputers/Python/tree/master/Snake_water_gun) — 蛇水枪（石头剪刀布变种）游戏
- [PingPong](https://github.com/geekcomputers/Python/tree/master/PingPong) — 乒乓球游戏
- [PongPong_Game](https://github.com/geekcomputers/Python/tree/master/PongPong_Game) — Pong 经典弹球游戏
- [Tic-Tac-Toe Games](https://github.com/geekcomputers/Python/tree/master/Tic-Tac-Toe%20Games) — 井字棋游戏
- [Wordle](https://github.com/geekcomputers/Python/tree/master/Wordle) — Wordle 猜词游戏
- [Industrial_developed_hangman](https://github.com/geekcomputers/Python/tree/master/Industrial_developed_hangman) — 高级猜词游戏（Hangman）
- [brickout-game](https://github.com/geekcomputers/Python/tree/master/brickout-game) — 打砖块游戏
- [game_of_life](https://github.com/geekcomputers/Python/tree/master/game_of_life) — 康威生命游戏
- [Street_Fighter](https://github.com/geekcomputers/Python/tree/master/Street_Fighter) — 街头霸王游戏
- [BoardGame-CLI](https://github.com/geekcomputers/Python/tree/master/BoardGame-CLI) — CLI 棋盘游戏合集

---

## GUI 应用与工具

带有图形界面的桌面应用，包括密码管理器、自动补全、菜单等工具。

- [Password Manager Using Tkinter](https://github.com/geekcomputers/Python/tree/master/Password%20Manager%20Using%20Tkinter) — 使用 Tkinter 实现的密码管理器
- [AutoComplete_App](https://github.com/geekcomputers/Python/tree/master/AutoComplete_App) — 自动补全应用
- [Quizzler Using Tkinter and Trivia DB API](https://github.com/geekcomputers/Python/tree/master/Quizzler%20Using%20Tkinter%20and%20Trivia%20DB%20API) — 使用 Tkinter 和 Trivia 数据库 API 的测验应用
- [Droplistmenu](https://github.com/geekcomputers/Python/tree/master/Droplistmenu) — 下拉菜单 GUI 组件
- [UI-Apps](https://github.com/geekcomputers/Python/tree/master/UI-Apps) — UI 桌面应用合集
- [Key_Binding](https://github.com/geekcomputers/Python/tree/master/Key_Binding) — 按键绑定工具
- [JustDialScrapperGUI](https://github.com/geekcomputers/Python/tree/master/JustDialScrapperGUI) — JustDial 爬虫 GUI 工具
- [Laundary System](https://github.com/geekcomputers/Python/tree/master/Laundary%20System) — 洗衣管理系统
- [Personal-Expense-Tracker](https://github.com/geekcomputers/Python/tree/master/Personal-Expense-Tracker) — 个人支出追踪器
- [Windows_Wallpaper_Script](https://github.com/geekcomputers/Python/tree/master/Windows_Wallpaper_Script) — Windows 壁纸设置脚本

---

## 安全与加密

密码生成、加密解密、数据校验等安全相关脚本。

- [Password Generator](https://github.com/geekcomputers/Python/tree/master/Password%20Generator) — 随机密码生成器
- [XORcipher](https://github.com/geekcomputers/Python/tree/master/XORcipher) — XOR 加密/解密工具
- [CRC](https://github.com/geekcomputers/Python/tree/master/CRC) — CRC 循环冗余校验实现
- [Password Manager Using Tkinter](https://github.com/geekcomputers/Python/tree/master/Password%20Manager%20Using%20Tkinter) — 安全存储密码的 GUI 管理器

---

## 机器学习与 AI

人脸识别、口罩检测、手势检测、语音助手等人工智能相关项目。

- [Face and eye Recognition](https://github.com/geekcomputers/Python/tree/master/Face%20and%20eye%20Recognition) — 人脸和眼睛识别
- [Face_Mask_detection (haarcascade)](https://github.com/geekcomputers/Python/tree/master/Face_Mask_detection%20(haarcascade)) — 基于 Haar 级联分类器的口罩检测
- [Hand-Motion-Detection](https://github.com/geekcomputers/Python/tree/master/Hand-Motion-Detection) — 手部动作检测
- [JARVIS](https://github.com/geekcomputers/Python/tree/master/JARVIS) — 语音控制 Windows 程序的语音助手
- [VoiceAssistant](https://github.com/geekcomputers/Python/tree/master/VoiceAssistant) — 语音助手
- [VoiceRepeater](https://github.com/geekcomputers/Python/tree/master/VoiceRepeater) — 语音重复器
- [QuestionAnswerVirtualAssistant](https://github.com/geekcomputers/Python/tree/master/QuestionAnswerVirtualAssistant) — 问答虚拟助手
- [ML](https://github.com/geekcomputers/Python/tree/master/ML) — 机器学习相关脚本和模型

---

## 算法与数据结构

排序算法、链表、二叉树、递归可视化、数学曲线等算法实现。

- [Sorting Algorithims](https://github.com/geekcomputers/Python/tree/master/Sorting%20Algorithims) / [Sorting Algorithms](https://github.com/geekcomputers/Python/tree/master/Sorting%20Algorithms) — 排序算法合集
- [LinkedLists all Types](https://github.com/geekcomputers/Python/tree/master/LinkedLists%20all%20Types) — 各类链表实现（单链表、双向链表、循环链表等）
- [binary_search_trees](https://github.com/geekcomputers/Python/tree/master/binary_search_trees) — 二叉搜索树实现
- [Recursion Visulaizer](https://github.com/geekcomputers/Python/tree/master/Recursion%20Visulaizer) — 递归算法可视化工具
- [Koch Curve](https://github.com/geekcomputers/Python/tree/master/Koch%20Curve) — 科赫雪花曲线绘制
- [Collatz Sequence](https://github.com/geekcomputers/Python/tree/master/Collatz%20Sequence) — 考拉兹猜想序列
- [Triplets with zero sum](https://github.com/geekcomputers/Python/tree/master/Triplets%20with%20zero%20sum) — 和为零的三元组查找
- [Electronics_Algorithms](https://github.com/geekcomputers/Python/tree/master/Electronics_Algorithms) — 电子学算法
- [linear-algebra-python](https://github.com/geekcomputers/Python/tree/master/linear-algebra-python) — Python 线性代数运算
- [floodfill](https://github.com/geekcomputers/Python/tree/master/floodfill) — 洪水填充算法
- [Patterns](https://github.com/geekcomputers/Python/tree/master/Patterns) — 图案生成算法

---

## 数学与工具

计算器、货币转换、秒表、字符计数等实用工具。

- [calculator.py](https://github.com/geekcomputers/Python/blob/master/calculator.py) — 使用 `eval()` 实现的命令行计算器
- [timymodule.py](https://github.com/geekcomputers/Python/blob/master/timymodule.py) — `timeit` 模块的替代方案，更易于使用
- [SimpleStopWatch.py](https://github.com/geekcomputers/Python/blob/master/SimpleStopWatch.py) — 简易秒表工具
- [CountMillionCharacter.py](https://github.com/geekcomputers/Python/blob/master/CountMillionCharacter.py) / [CountMillionCharacters-2.0.py](https://github.com/geekcomputers/Python/blob/master/CountMillionCharacters-2.0.py) — 统计文本文件字符数
- [CountMillionCharacters-Variations](https://github.com/geekcomputers/Python/tree/master/CountMillionCharacters-Variations) — 字符计数算法的多种变体实现
- [currency converter](https://github.com/geekcomputers/Python/tree/master/currency%20converter) — 货币转换工具
- [NumberToNumberName](https://github.com/geekcomputers/Python/tree/master/NumberToNumberName) — 数字转名称（如 123 转 "一百二十三"）

---

## 社交与通信

聊天应用、社交监控、推文发送等通信相关脚本。

- [tweeter.py](https://github.com/geekcomputers/Python/blob/master/tweeter.py) — 从终端发送推文或图片
- [whatsapp-monitor.py](https://github.com/geekcomputers/Python/blob/master/whatsapp-monitor.py) — 使用 Selenium 在终端显示 WhatsApp 联系人在线状态
- [Python_chatting_application](https://github.com/geekcomputers/Python/tree/master/Python_chatting_application) — Python 聊天应用
- [communication](https://github.com/geekcomputers/Python/tree/master/communication) — 通信相关工具脚本

---

## 其他实用脚本

不便归类但同样实用的脚本和项目。

- [xkcd_downloader.py](https://github.com/geekcomputers/Python/blob/master/xkcd_downloader.py) — 下载最新 XKCD 漫画到 comics 文件夹
- [Automated Scheduled Call Reminders](https://github.com/geekcomputers/Python/tree/master/Automated%20Scheduled%20Call%20Reminders) — 定时呼叫提醒系统
- [QR_code_generator](https://github.com/geekcomputers/Python/tree/master/QR_code_generator) — 二维码生成器
- [bank_managment_system](https://github.com/geekcomputers/Python/tree/master/bank_managment_system) — 银行管理系统
- [cli_master](https://github.com/geekcomputers/Python/tree/master/cli_master) — CLI 工具大师合集
- [framework](https://github.com/geekcomputers/Python/tree/master/framework) — 小型框架
- [libs](https://github.com/geekcomputers/Python/tree/master/libs) — 可复用的库合集
- [Python Programs](https://github.com/geekcomputers/Python/tree/master/Python%20Programs) — Python 程序合集
- [Assembler](https://github.com/geekcomputers/Python/tree/master/Assembler) — 汇编器实现

---

## 开发指南

- [DEVELOPMENT.md](https://github.com/geekcomputers/Python/blob/master/DEVELOPMENT.md) — 项目开发指南
- [CONTRIBUTING.md](https://github.com/geekcomputers/Python/blob/master/CONTRIBUTING.md) — 贡献者指南

---

## 使用提示

### 适合初学者入门

本仓库是 Python 初学者的绝佳学习资源。每个脚本都是独立运行的单个文件或小项目，建议按以下方式学习：

1. **从简单脚本入手**：先阅读 `calculator.py`、`osinfo.py`、`fileinfo.py` 等单文件脚本，理解基础语法
2. **运行并修改**：克隆仓库后直接在本地运行脚本，尝试修改参数观察效果
3. **查看分类学习方向**：根据兴趣选择分类深入学习，如对游戏开发感兴趣可重点研究 `Flappy Bird`、`Snake Game` 等项目

### 如何运行脚本

```bash
# 克隆仓库
git clone https://github.com/geekcomputers/Python.git
cd Python

# 安装依赖（部分脚本需要）
pip install -r requirements.txt  # 如果存在

# 直接运行脚本
python calculator.py
python fileinfo.py
```

### 注意事项

1. **依赖检查**：部分脚本依赖外部库（如 `BeautifulSoup`、`Selenium`、`pygame`、`tkinter` 等），运行前请确认 `requirements.txt` 或脚本头部导入的依赖已安装
2. **路径问题**：某些脚本使用硬编码路径（如 `server_list.txt`、`testdir`），运行前请根据实际环境修改
3. **权限问题**：涉及系统操作的脚本（如 `changemac.py` 修改 MAC 地址）可能需要管理员/root权限
4. **API 限制**：调用外部 API 的脚本（如 `Google_News.py`、`tweeter.py`）可能受 API 调用频率限制或需要认证密钥
5. **时效性**：部分爬虫脚本因目标网站结构变化可能失效，需要根据实际情况调整解析逻辑
6. **安全性**：部分脚本使用 `eval()`（如 `calculator.py`），处理不可信输入时存在安全风险，仅供学习参考

---

> 本文档由 AI 自动生成，链接指向 GitHub 仓库最新版本。如链接失效，请访问 [https://github.com/geekcomputers/Python](https://github.com/geekcomputers/Python) 查看最新目录结构。
