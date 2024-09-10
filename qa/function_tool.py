import base64
from typing import Callable, List, Dict, Tuple
import time
import json
import json5
from client.clientfactory import Clientfactory
from zhipuai import ZhipuAI
from qa.purpose_type import userPurposeType
from pathlib import Path
from ppt_docx.ppt_generation import generate as generate_ppt
from ppt_docx.ppt_content import generate_ppt_content
from ppt_docx.docx_generation import generate_docx_content as generate_docx
from ppt_docx.docx_content import generate_docx_content
from rag import rag_chain
from audio.audio_extract import (
    extract_text,
    extract_language,
    extract_gender,
    get_tts_model_name,
)
from audio.audio_generate import audio_generate


def is_file_path(path):
    return Path(path).exists()


from Internet.Internet_chain import InternetSearchChain
from kg.Graph import GraphDao

from qa.purpose_type import userPurposeType
from model.KG.search_model import _Value

_dao = GraphDao()


def relation_tool(entities: List[Dict] | None) -> str | None:
    if not entities or len(entities) == 0:
        return None

    relationships = set()  # 使用集合来避免重复关系
    relationship_match = []

    # 遍历每个实体并查询与其他实体的关系
    for entity in entities:
        entity_name = entity["name"]
        if entity["label"] == "Disease":
            for k, v in entity.items():
                relationships.add(f"{entity_name} {k}: {v}")

        # 查询每个实体与其他实体的关系
        relationship_match.append(_dao.query_relationship_by_person_name(entity_name))

    for i in range(len(relationship_match)):
        for record in relationship_match[i]:
            # 获取起始节点和结束节点的名称

            start_name = record["r"].start_node["name"]
            end_name = record["r"].end_node["name"]

            # 获取关系类型
            rel = type(record["r"]).__name__  # 获取关系的类名，比如 CAUSES

            # # 获取关系的备注信息，假设关系中可能有一个 'Notes' 属性
            # notes = getattr(record['r'], 'Notes', '无')

            # 构建关系字符串，打印或存储关系信息
            print(f"{start_name} {rel} {end_name}")

            # 构建关系字符串并添加到集合，确保不会重复添加
            relationships.add(f"{start_name} {rel} {end_name}")

    # 返回关系集合的内容
    if relationships:
        return "；".join(relationships)
    else:
        return None


# 处理Unkown问题的函数
def process_unknown_tool(
    question_type: userPurposeType,
    question: str,
    history: List[List | None] = None,
    image_url=None,
):
    response = Clientfactory().get_client().chat_with_ai_stream(question, history)
    return (response, question_type)


# 处理RAG问题
def RAG_tool(
    question_type: userPurposeType,
    question: str,
    history: List[List | None] = None,
    image_url=None,
):
    # 先利用question去检索得到docs
    response = rag_chain.invoke(question, history)
    return (response, question_type)


# 处理ImageGeneration问题的函数
def process_images_tool(question_type, question, history, image_url=None):
    client = Clientfactory.get_special_client(client_type=question_type)
    response = client.images.generations(
        model="cogview-3",  # 填写需要调用的模型编码
        prompt=question,
    )
    print(response.data[0].url)
    return (response.data[0].url, question_type)


def process_image_describe_tool(question_type, question, history, image_url=None):
    if len(question)==0:
        question = "描述这个图片，说明这个图片的主要内容"

    img_path = image_url[0]
    client = Clientfactory.get_special_client(client_type=question_type)
    if is_file_path(img_path):
        with open(img_path, "rb") as img_file:
            img_base = base64.b64encode(img_file.read()).decode("utf-8")
            response = client.chat.completions.create(
                model="glm-4v-plus",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": img_base}},
                            {"type": "text", "text": question},
                        ],
                    }
                ],
            )
        return (response.choices[0].message.content, question_type)
    else:
        response = client.chat.completions.create(
            model="glm-4v-plus",  # 填写需要调用的模型名称
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {
                            "type": "text",
                            "text": "图里有什么？请描述图里的主要内容",
                        },
                    ],
                }
            ],
        )
        return (response.choices[0].message.content, question_type)


def process_ppt_tool(
    question_type, question: str, history: List[List[str] | None] = None, image_url=None
) -> Tuple[Tuple[str, str], userPurposeType]:
    raw_text: str = generate_ppt_content(question, history)
    ppt_content = json5.loads(raw_text)
    ppt_file: str = generate_ppt(
        ppt_content
    )  # 这个语句由于模型能力有限，可能不会按照格式输出，会导致冲突，要用str正则语句修改，删除一些异常符号，否则会出bug
    return (ppt_file, "ppt"), userPurposeType.PPT


def process_docx_tool(
    question_type, question: str, history: List[List[str] | None] = None, image_url=None
) -> Tuple[Tuple[str, str], userPurposeType]:
    # 先生成word的文案
    raw_text: str = generate_docx_content(question, history)
    docx_content = json.loads(raw_text)
    docx_file: str = generate_docx(docx_content)
    return (docx_file, "docx"), userPurposeType.Docx


def process_text_video_tool(question_type, question, history, image_url=None):
    client = Clientfactory.get_special_client(client_type=question_type)
    chatRequest = client.videos.generations(
        model="cogvideox",
        prompt=question,
    )
    print(chatRequest)

    start_time = time.time()  # 开始计时
    video_url = None
    timeout = 120
    while time.time() - start_time < timeout:
        # 请求视频生成结果
        print(chatRequest.id)
        response = client.videos.retrieve_videos_result(id=chatRequest.id)

        # 检查任务状态是否成功
        if response.task_status == "SUCCESS" and response.video_result:
            video_url = response.video_result[0].url
            print("视频URL:", video_url)
            return ((video_url, "视频"), question_type)
        else:
            print("任务未完成，请等待...")

        # 等待一段时间再请求
        time.sleep(2)  # 每次请求后等待2秒再继续

    return (None, question_type)


# 处理audio问题的函数
def process_audio_tool(
    question_type: userPurposeType,
    question: str,
    history: List[List | None] = None,
    image_url=None,
):
    # 先让大语言模型生成需要转换成语音的文字
    text = extract_text(question, history)
    # 判断需要生成哪种语言（东北、陕西、粤...）
    lang = extract_language(question)
    # 判断需要生成男声还是女声
    gender = extract_gender(question)
    # 上面三步均与大语言模型进行交互

    # 选择用于生成的模型
    model_name, success = get_tts_model_name(lang=lang, gender=gender)
    if success:
        audio_file = audio_generate(text, model_name)
    else:
        audio_file = audio_generate(
            "由于目标语言包缺失，我将用普通话回复您。" + text, model_name
        )
    return ((audio_file, "audio"), question_type)


# 处理联网搜索问题的函数
def process_InternetSearch_tool(
    question_type: userPurposeType,
    question: str,
    history: List[List | None] = None,
    image_url=None,
):
    response, links, success = InternetSearchChain(question, history)
    return (response, question_type, links, success)


QUESTION_TO_FUNCTION = {
    userPurposeType.Unknown: process_unknown_tool,
    userPurposeType.Document: RAG_tool,
    userPurposeType.ImageGeneration: process_images_tool,
    userPurposeType.Audio: process_audio_tool,
    userPurposeType.InternetSearch: process_InternetSearch_tool,
    userPurposeType.ImageDescribe: process_image_describe_tool,
    userPurposeType.PPT: process_ppt_tool,
    userPurposeType.Docx: process_docx_tool,
    userPurposeType.Video: process_text_video_tool,
}


# 根据用户不同的意图选择不同的函数
def map_question_to_function(purpose: userPurposeType) -> Callable:
    if purpose in QUESTION_TO_FUNCTION:
        return QUESTION_TO_FUNCTION[purpose]
    else:
        raise ValueError("没有找到意图对应的函数")
