from qa.answer import get_answer
from qa.function_tool import process_image_describe_tool
from qa.purpose_type import userPurposeType
from client.LLMclientgeneric import LLMclientgeneric
from audio.audio_generate import audio_generate

import PyPDF2
import chardet
import mimetypes
import gradio as gr
from icecream import ic
from docx import Document
from pydub import AudioSegment
import speech_recognition as sr
from opencc import OpenCC


AVATAR = ("resource/user.png", "resource/bot.jpg")


# pip install zhconv
# pip install whisper
# pip install openai-whisper
# pip install wheel
# pip install soundfile
# pip install pydub
# pip install opencc-python-reimplemented


def convert_to_simplified(text):
    converter = OpenCC("t2s")
    return converter.convert(text)


def convert_audio_to_wav(audio_file_path):
    audio = AudioSegment.from_file(audio_file_path)  # 自动识别格式
    wav_file_path = audio_file_path.rsplit(".", 1)[0] + ".wav"  # 生成 WAV 文件路径
    audio.export(wav_file_path, format="wav")  # 将音频文件导出为 WAV 格式
    return wav_file_path


def audio_to_text(audio_file_path):
    # 创建识别器对象
    # 如果不是 WAV 格式，先转换为 WAV
    if not audio_file_path.endswith(".wav"):
        audio_file_path = convert_audio_to_wav(audio_file_path)

    recognizer = sr.Recognizer()
    with sr.AudioFile(audio_file_path) as source:
        audio_data = recognizer.record(source)
        # 使用 Google Web Speech API 进行语音识别
        # text = recognizer.recognize_google(audio_data, language="zh-CN")  # 使用中文
        text = recognizer.recognize_whisper(audio_data, language="zh")
        text_simplified = convert_to_simplified(text)
    return text_simplified


# pip install PyPDF2
def pdf_to_str(pdf_file):
    reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    return text


def docx_to_str(file_path):
    doc = Document(file_path)
    text = []
    for paragraph in doc.paragraphs:
        text.append(paragraph.text)
    return "\n".join(text)


# pip install chardet
def text_file_to_str(text_file):
    with open(text_file, "rb") as file:
        raw_data = file.read()
        result = chardet.detect(raw_data)
        encoding = result["encoding"]

    # 使用检测到的编码来读取文件
    with open(text_file, "r", encoding=encoding) as file:
        return file.read()


# 核心函数
def grodio_view(chatbot, chat_input):

    # 用户消息立即显示
    user_message = chat_input["text"]
    bot_response = "loading..."
    chatbot.append([user_message, bot_response])
    yield chatbot

    files = chat_input["files"]
    audios = []
    images = []
    pdfs = []
    docxs = []
    texts = []

    for file in files:
        file_type, _ = mimetypes.guess_type(file)
        if file_type.startswith("audio/"):
            audios.append(file)
        elif file_type.startswith("image/"):
            images.append(file)
        elif file_type.startswith("application/pdf"):
            pdfs.append(file)
        elif file_type.startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            docxs.append(file)
        elif file_type.startswith("text/"):
            texts.append(file)
        else:
            user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'该文件为不支持的文件类型'"
            print(f"Unknown file type: {file_type}")

    # 音频解析逻辑示例
    if audios != []:
        for i, audio in enumerate(audios):
            audio_message = audio_to_text(audio)
            if audio_message == "":
                user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'音频识别失败，请稍后再试'"
            elif "作曲" in audio_message:
                user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'不好意思，我无法理解音乐'"
            else:
                user_message += f"音频{i+1}内容：{audio_message}"

    if images != []:
        image_url = images
    else:
        image_url = None

    if pdfs != []:
        for i, pdf in enumerate(pdfs):
            pdf_text = pdf_to_str(pdf)
            user_message += f"PDF{i+1}内容：{pdf_text}"

    if docxs != []:
        for i, docx in enumerate(docxs):
            docx_text = docx_to_str(docx)
            user_message += f"DOCX{i+1}内容：{docx_text}"

    if texts != []:
        for i, text in enumerate(texts):
            text_string = text_file_to_str(text)
            user_message += f"文本{i+1}内容：{text_string}"

    if user_message == "":
        user_message = "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'请问您有什么想了解的，我将尽力为您服务'"
    answer = get_answer(user_message, chatbot, image_url)
    bot_response = ""

    # 处理文本生成/其他/文档检索
    if answer[1] == userPurposeType.Unknown or answer[1] == userPurposeType.Document:
        # 流式输出
        for chunk in answer[0]:
            bot_response = bot_response + (chunk.choices[0].delta.content or "")
            chatbot[-1][1] = bot_response
            yield chatbot

    # 处理图片生成
    if answer[1] == userPurposeType.ImageGeneration:
        image_url = answer[0]
        describe = process_image_describe_tool(
            question_type=userPurposeType.ImageDescribe,
            question="描述这个图片，不要识别‘AI生成’",
            history=" ",
            image_url=image_url,
        )
        combined_message = f"""
        <div>
            <p>生成的图片：</p>
            <img id="myImage" src="{image_url}" alt="Generated Image" style="max-width: 100%; height: auto; cursor: pointer;" />
            <p>{describe[0]}</p>
        </div>
        """
        chatbot[-1][1] = combined_message
        yield chatbot

    # 处理图片描述
    if answer[1] == userPurposeType.ImageDescribe:
        output_message = answer[0]
        for i in range(0, len(output_message)):
            bot_response = output_message[: i + 1]
            chatbot[-1][1] = bot_response
            yield chatbot

    # 处理视频
    if answer[1] == userPurposeType.Video:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = "抱歉，视频生成失败，请稍后再试"
        yield chatbot

    # 处理PPT
    if answer[1] == userPurposeType.PPT:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = "抱歉，PPT生成失败，请稍后再试"
        yield chatbot
        
    # 处理Docx
    if answer[1] == userPurposeType.Docx:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = "抱歉，文档生成失败，请稍后再试"
        yield chatbot

    # 处理音频生成
    if answer[1] == userPurposeType.Audio:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = "抱歉，音频生成失败，请稍后再试"
        yield chatbot

    # 处理联网搜索
    if answer[1] == userPurposeType.InternetSearch:
        if answer[3] == False:
            output_message = (
                "由于网络问题，访问互联网失败，下面由我根据现有知识给出回答："
            )
        else:
            # 将字典中的内容转换为 Markdown 格式的链接
            links = "\n".join(f"[{title}]({link})" for link, title in answer[2].items())
            links += "\n"
            output_message = f"参考资料：{links}"
        for i in range(0, len(output_message)):
            bot_response = output_message[: i + 1]
            chatbot[-1][1] = bot_response
            yield chatbot
        for chunk in answer[0]:
            bot_response = bot_response + (chunk.choices[0].delta.content or "")
            chatbot[-1][1] = bot_response
            yield chatbot


def gradio_audio_view(chatbot, audio_input):

    # 用户消息立即显示
    if audio_input is None:
        user_message = ""
    else:
        user_message = (audio_input, "audio")
    bot_response = "loading..."
    chatbot.append([user_message, bot_response])
    yield chatbot

    if audio_input is None:
        audio_message = "无音频"
    else:
        audio_message = audio_to_text(audio_input)

    chatbot[-1][0] = audio_message

    user_message = ""
    if audio_message == "无音频":
        user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'欢迎与我对话，我将用语音回答您'"
    elif audio_message == "":
        user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'音频识别失败，请稍后再试'"
    elif "作曲 作曲" in audio_message:
        user_message += "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'不好意思，我无法理解音乐'"
    else:
        user_message += audio_message

    if user_message == "":
        user_message = "请你将下面的句子修饰后输出，不要包含额外的文字，句子:'请问您有什么想了解的，我将尽力为您服务'"


    answer = get_answer(user_message, chatbot)
    bot_response = ""

    # 处理文本生成/其他/文档检索
    if answer[1] == userPurposeType.Unknown or answer[1] == userPurposeType.Document:
        # 语音输出
        for chunk in answer[0]:
            # 获取每个块的数据
            chunk_content = (chunk.choices[0].delta.content or "")
            bot_response += chunk_content

        chatbot[-1][1] = (
            audio_generate(
                text=bot_response,
                model_name="zh-CN-YunxiNeural",
            ),
            "audio",
        )
        yield chatbot

    # 处理图片生成
    if answer[1] == userPurposeType.ImageGeneration:
        image_url = answer[0]
        describe = process_image_describe_tool(
            question_type=userPurposeType.ImageDescribe,
            question="描述这个图片，不要识别‘AI生成’",
            history=" ",
            image_url=image_url,
        )
        combined_message = f"""
        <div>
            <p>生成的图片：</p>
            <img id="myImage" src="{image_url}" alt="Generated Image" style="max-width: 100%; height: auto; cursor: pointer;" />
            <p>{describe[0]}</p>
        </div>
        """
        chatbot[-1][1] = combined_message
        yield chatbot

        # 处理视频
    if answer[1] == userPurposeType.Video:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = (
                audio_generate(
                    text="抱歉，视频生成失败，请稍后再试",
                    model_name="zh-CN-YunxiNeural",
                ),
                "audio",
            )
        yield chatbot

    # 处理PPT
    if answer[1] == userPurposeType.PPT:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = (
                audio_generate(
                    text="抱歉，PPT生成失败，请稍后再试",
                    model_name="zh-CN-YunxiNeural",
                ),
                "audio",
            )
        yield chatbot

    # 处理音频生成
    if answer[1] == userPurposeType.Audio:
        if answer[0] is not None:
            chatbot[-1][1] = answer[0]
        else:
            chatbot[-1][1] = (
                audio_generate(
                    text="抱歉，音频生成失败，请稍后再试",
                    model_name="zh-CN-YunxiNeural",
                ),
                "audio",
            )
        yield chatbot

    # 处理联网搜索
    if answer[1] == userPurposeType.InternetSearch:
        if answer[3] == False:
            bot_response = (
                "由于网络问题，访问互联网失败，下面由我根据现有知识给出回答："
            )
        # 语音输出
        for chunk in answer[0]:
            # 获取每个块的数据
            chunk_content = (chunk.choices[0].delta.content or "")
            bot_response += chunk_content

        chatbot[-1][1] = (
            audio_generate(
                text=bot_response,
                model_name="zh-CN-YunxiNeural",
            ),
            "audio",
        )
        yield chatbot


# 切换到语音模式的函数
def toggle_voice_mode():
    return (
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=True),
    )


# 切换回文本模式的函数
def toggle_text_mode():
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=True),
        gr.update(visible=False),
        gr.update(visible=False),
    )


examples = [
    {"text": "您好", "files": []},
    {"text": "我想了解糖尿病相关知识", "files": []},
    {"text": "糖尿病人适合吃的食物有哪些？", "files": []},
    {"text": "糖尿病的常见症状有哪些？", "files": []},
    {
        "text": "帮我生成一份有关糖尿病发病原因，症状，治疗药物，预防措施的PPT",
        "files": [],
    },
    {"text": "请根据我给的就诊信息单，给我一个合理化饮食建议", "files": []},
    {"text": "我最近想打太极养生，帮我生成一段老人打太极的视频吧", "files": []},
    {"text": "帮我生成一张老人练太极图片", "files": []},
    {"text": "用语音重新回答我一次", "files": []},
    {"text": "根据文献帮我快速入门git", "files": []},
    {"text": "搜索一下最新新闻", "files": []},
]


# 构建 Gradio 界面
with gr.Blocks() as demo:
    # 标题和描述
    gr.Markdown("# 「赛博华佗」📒\n你的健康小助手")

    # 创建聊天布局
    with gr.Row():
        with gr.Column(scale=10):
            chatbot = gr.Chatbot(
                height=600, avatar_images=AVATAR, show_copy_button=True
            )

    with gr.Row():
        with gr.Column(scale=9):
            chat_input = gr.MultimodalTextbox(
                interactive=True,
                file_count="multiple",
                placeholder="输入消息或上传文件...",
                show_label=False,
            )
            audio_input = gr.Audio(
                sources=["microphone","upload"], label="录音输入", visible=False, type="filepath"
            )
        with gr.Column(scale=1):
            clear = gr.ClearButton([chatbot, chat_input, audio_input], value="清除记录")
            toggle_voice_button = gr.Button("语音对话模式", visible=True)
            toggle_text_button = gr.Button("文本交流模式", visible=False)
            submit_audio_button = gr.Button("发送", visible=False)

    with gr.Row() as example_row:
        example_component = gr.Examples(
            examples=examples, inputs=chat_input, visible=True
        )

    chat_input.submit(fn=grodio_view, inputs=[chatbot, chat_input], outputs=[chatbot])
    # 切换按钮点击事件
    toggle_voice_button.click(
        fn=toggle_voice_mode,
        inputs=None,
        outputs=[
            chat_input,
            audio_input,
            toggle_voice_button,
            toggle_text_button,
            submit_audio_button,
        ],
    )

    toggle_text_button.click(
        fn=toggle_text_mode,
        inputs=None,
        outputs=[
            chat_input,
            audio_input,
            toggle_voice_button,
            toggle_text_button,
            submit_audio_button,
        ],
    )

    submit_audio_button.click(
        fn=gradio_audio_view, inputs=[chatbot, audio_input], outputs=[chatbot]
    )

# 启动应用
demo.launch()
