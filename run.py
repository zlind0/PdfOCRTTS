import os
import fitz  # pip install --upgrade pip; pip install --upgrade pymupdf
from tqdm import tqdm # pip install tqdm
# import ollama
import base64, requests, re, subprocess
import threading

workdir = "."
modelname = "mlx-community/Nanonets-OCR-s-bf16"
api_key = "key"

prompt = "ocr图片并输出markdown，忽略页码，忽略脚注，忽略注释"
ollama_url = "http://localhost:1234/v1/chat/completions"

# system_prompt = """Extract the text from the above document as if you were reading it naturally. Return the equations in LaTeX representation. If there is an image in the document and image caption is not present, add a small description of the image inside the <img></img> tag; otherwise, add the image caption inside <img></img>. Watermarks should be wrapped in brackets. Ex: <watermark>OFFICIAL COPY</watermark>. Page numbers should be wrapped in brackets. Ex: <page_number>14</page_number> or <page_number>9/22</page_number>. Prefer using ☐ and ☑ for check boxes. Delete all footnotes."""

# def perform_ocr(imgpath):
#     # 使用本地的ollama
#     response = ollama.chat(
#         model=modelname,
#         messages=[
#             {"role": "user", "content": prompt, "images": [os.path.abspath(pixpath)]}
#         ],
#     )
#     return str(response['message']['content'])

def perform_http_ocr(pixmap):
    # 使用OpenAI-compatible API来处理OCR
    try:
        img_bytes = pixmap.tobytes("png")
        base64_image = base64.b64encode(img_bytes).decode('utf-8')
        payload = {
            "model": modelname,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{base64_image}"
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 10000
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        response = requests.post(
            ollama_url,  # 或兼容的本地端点
            json=payload,
            headers=headers,
            timeout=300
        )
        response.raise_for_status()
        result = response.json()
        ocr_result = result['choices'][0]['message']['content']
        
        return ocr_result.strip()
    
    except requests.exceptions.RequestException as e:
        return f"Request failed: {str(e)}"
    except Exception as e:
        return f"Error occurred: {str(e)}"
    
def gen_tts(f, root_dir):
    # 异步调用macos的say命令完成TTS
    def run_tts(f, root_dir):
        if not os.path.exists(f"{root_dir}/{f}.mp3"):
            cmd_say=["say","-f",f"{root_dir}/{f}.md",\
                    "-o",f"{root_dir}/{f}.aiff"]
            subprocess.run(cmd_say)
            cmd_ffmpeg=["ffmpeg","-i",f"{root_dir}/{f}.aiff","-b:a","64k","-ac","1",
                        "-id3v2_version","3","-metadata",f'artist=EPUB_OCR',\
                        "-metadata",f'album={root_dir}',\
                        f"{root_dir}/{f}.mp3"]
            subprocess.run(cmd_ffmpeg)
            subprocess.run(["rm",f"{root_dir}/{f}.aiff"])

    thread = threading.Thread(target=run_tts, args=(f, root_dir))
    thread.daemon = True  # 可选：设置为守护线程（主程序退出时自动结束）
    thread.start()

def purify_pagetxt(text):
    # 去除脚注

    # 定义圆圈数字字符集
    circle_nums = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
    
    # 编译正则表达式模式：
    # 1. 匹配括号数字：如 (1) [2] <3>
    bracket_pattern = re.compile(r'^[(\[<]\d+[)\]>]')
    # 2. 匹配数字+空格：如 "1   "
    digit_space_pattern = re.compile(r'^\d+\s+')
    
    # 分割文本为行列表
    lines = text.splitlines()
    # 从最后一行开始向前扫描
    i = len(lines) - 1
    while i >= 0:
        line = lines[i]
        # 检查三种匹配条件：
        # 1. 以圆圈数字开头
        # 2. 匹配括号数字模式
        # 3. 匹配数字+空格模式
        if line.startswith(tuple(circle_nums)) or \
           bracket_pattern.match(line) or \
           digit_space_pattern.match(line) or \
            len(line.strip())==0 or \
            line.strip()=="---" or \
            line.startswith("|") or line.startswith("<"):
            i -= 1  # 继续检查前一行
        else:
            break  # 遇到非特殊行时停止
    
    # 保留非特殊行（0到i+1）
    result_lines = lines[:i+1]
    # 重新组合文本
    return '\n'.join(result_lines)

def has_repeated_phrase_at_end(text, min_repeat=5, max_phrase_length=30):
    """
    检查文本末尾是否有短语重复多次
    :param text: 要检查的文本
    :param min_repeat: 最小重复次数（默认5次）
    :param max_phrase_length: 短语最大长度（默认30字）
    :return: 如果存在重复短语返回True，否则返回False
    """
    n = len(text)
    if n < min_repeat:  # 文本太短无法重复
        return False
    
    # 遍历所有可能的短语长度（1到max_phrase_length）
    for phrase_len in range(1, max_phrase_length + 1):
        required_length = min_repeat * phrase_len
        if n < required_length:
            continue  # 文本长度不足
        
        # 提取末尾需要检查的片段
        segment = text[-required_length:]
        
        # 检查片段是否满足周期性（重复特征）
        is_periodic = True
        for j in range(0, required_length - phrase_len):
            if segment[j] != segment[j + phrase_len]:
                is_periodic = False
                break
        
        if is_periodic:
            return True
    
    return False

for each_path in os.listdir(workdir):
    if ".pdf" in each_path:
        doc = fitz.Document((os.path.join(workdir, each_path)))
        pdfdatapath = os.path.join(workdir, each_path.replace(".pdf",""))
        if not os.path.exists(pdfdatapath):
            os.mkdir(pdfdatapath)

        for i in tqdm(range(len(doc)), desc="pages"):
            for img in doc.get_page_images(i):
                xref = img[0]
                response_mdpath = os.path.join(pdfdatapath, "p%04d-%s.md" % (i, xref))
                if os.path.exists(response_mdpath) or os.path.exists(os.path.join(pdfdatapath, "p%04d-%s.mp3" % (i, xref))):
                    continue
                image = doc.extract_image(xref)
                pix = fitz.Pixmap(doc, xref)
                pixpath = os.path.join(pdfdatapath, "p%04d-%s.png" % (i, xref))
                pix.save(pixpath)
                
                response_txt = perform_http_ocr(pix)
                if has_repeated_phrase_at_end(response_txt):
                    # 防止LLM OCR识别中出现无限重复，如果有，再做一次，还是有的话就放弃
                    response_txt = perform_http_ocr(pix)
                
                with open(response_mdpath+".orig", "w") as f:
                    f.write(response_txt)
                with open(response_mdpath, "w") as f:
                    f.write(purify_pagetxt(response_txt))
                gen_tts("p%04d-%s" % (i, xref), each_path.replace(".pdf",""))

print("Done!")