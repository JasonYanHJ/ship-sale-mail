import pdfplumber
from pdfplumber.page import Page
from pdfplumber.pdf import PDF
from pdfplumber._typing import T_obj_list

from ...utils.logger import get_logger

logger = get_logger("extra_procure")


def process_procure_pdf(pdf_path: str) -> dict:
    """
    处理PDF文件，提取表格数据。

    Args:
        pdf_path (str): PDF文件的路径。
    Returns:
        dict: 返回一个字典，包含以下键：
            - 'table_data': list[list[str]] - 表格数据
            - 'meta_data': list[dict] - 附件元数据的键值对数据
    """

    try:
        meta_data = {}
        table_data = []

        with pdfplumber.open(pdf_path) as pdf:
            try:
                # 获取表格数据
                table_data = extract_table_data(pdf)

                # 提取元数据中"Description"部分的数据，并更新元数据
                description_data = extract_description_data(pdf)
                meta_data.update(description_data)

            except Exception as e:
                logger.error(
                    f"Error processing {pdf_path}: {e}")

    except Exception as e:
        logger.error(f"Error opening PDF {pdf_path}: {e}")
        return None

    return {
        'meta_data': meta_data,
        'table_data': table_data,
    }


def extract_table_data(pdf: PDF) -> list[list[list[str]]]:
    """
    从PDF中提取表格数据，每张表格对应一个section。

    Args:
        pdf (PDF): PDF对象。
    Returns:
        list[list[list[str]]: 返回表格数据(list[list[str])的数组，每个section对应一张表格
    """

    try:
        results = []
        section_result = []
        items_line = None  # 首先找到“Items”行，再开始提取

        for i, page in enumerate(pdf.pages):
            # 寻找“Items”字样
            if not items_line:
                lines = page.extract_text_lines()
                for line in lines:
                    if line['text'].startswith("Items") and "Helvetica" in line['chars'][0]['fontname']:
                        items_line = line

            # 如果没有找到过，代表还没有出现需要解析的表格，跳过这一页
            if not items_line:
                continue

            # 开始提取表格
            # 1. 裁剪页面到表格区域，对于第一页，使用items_bottom+4作为top
            if i+1 == items_line['chars'][0]['page_number']:
                # "Items"字样在页面底部，裁剪大小为负数时，直接跳过这一页处理
                if (items_line['bottom']+4) >= (page.height-36):
                    continue
                cropped_page = page.crop(
                    (16, items_line['bottom']+4, page.width-16, page.height-36))
            else:
                cropped_page = page.crop(
                    (16, 16, page.width-16, page.height-36))
            # 2. 提取表格数据
            table_data = cropped_page.extract_table({
                "explicit_vertical_lines": curves_to_edges(cropped_page.curves),
                "explicit_horizontal_lines": curves_to_edges(cropped_page.curves),
                "intersection_tolerance": 15,
            })
            # 3. 根据首个单元格是否以Equipment开头，划分多个表格
            if table_data:
                for row in table_data:
                    # 跳过空行
                    if all(not cell for cell in row):
                        continue
                    # 新的section，则将section加入results并重设section；否则继续追加
                    if row[0] and row[0].startswith('Equipment'):
                        if section_result:
                            results.append(section_result)
                        section_result = [row]
                    else:
                        section_result.append(row)

        # 将最后一张表添加到返回结果中
        if section_result:
            results.append(section_result)

        return results

    except Exception as e:
        logger.error(f"Error extracting tables: {e}")
        return []


def curves_to_edges(cs):
    edges = []
    for c in cs:
        edges += pdfplumber.utils.rect_to_edges(c)
    return edges


def extract_description_data(pdf: PDF) -> dict:
    """
    从页面中提取"description"部分的键值对数据。

    Args:
        pdf (PDF): PDF对象。
    Returns:
        dict: 返回"description"部分的键值对字典。如果未找到，则返回空字典。
    """
    try:
        for page in pdf.pages:
            # 查询以'Description:'开头的主题行，以及可能的由主题过长导致的后续行
            lines = page.extract_text_lines()
            description_lines_start_index = -1
            description_lines_end_index = -1
            for i, line in enumerate(lines):
                if line['text'].startswith("Description:"):
                    description_lines_start_index = i
                    break
            for i, line in enumerate(lines[(description_lines_start_index+1):]):
                # 后续行的字体都不是Helvetica
                if "Helvetica" in line['chars'][0]['fontname']:
                    description_lines_end_index = i + 1 + description_lines_start_index
                    break

            if description_lines_start_index == -1 or description_lines_end_index == -1:
                continue
            description_lines = lines[description_lines_start_index:description_lines_end_index]

            return extract_dict_from_lines_by_font(page, description_lines)

        return {}
    except Exception as e:
        logger.error(f"Error extracting subject: {e}")
        return {}


def extract_dict_from_lines_by_font(page: Page, lines: T_obj_list) -> dict:
    """
    从页面中的文本行提取键值对字典，使用字体类型区分键和值。

    Args:
        page (Page): PDF页面对象。
        lines (T_obj_list): 页面中的文本行列表。
    Returns:
        dict: 返回一个包含键值对的字典，键和值根据字体类型区分。
    """
    words = []

    for line in lines:
        bbox = pdfplumber.utils.obj_to_bbox(line)
        words.extend(page.crop(bbox).extract_words(
            return_chars=True, x_tolerance=2))

    return extract_dict_from_words_by_font(words)


def extract_dict_from_words_by_font(words: T_obj_list) -> dict:
    """
    从单词列表中提取键值对字典，使用字体类型区分键和值。

    Args:
        words (T_obj_list): 单词列表，每个单词包含文本以及字符列表，每个字符包含字体信息。
    Returns:
        dict: 返回一个包含键值对的字典，键和值根据字体类型区分。
    """

    result = {}
    item = dict(key="", value="")
    state = "key"  # 当前是key还是value

    for word in words:
        font_name = word['chars'][0]['fontname']
        text = word.get('text', '')
        text += ' '  # 单词之间使用空格分割，多余的空格后续会消除

        # 判断字体类型
        if 'Bold' in font_name:
            # 如果当前状态是value且有内容，则保存之前的键值对
            if state == 'value' and item['key'] and item['value']:
                # 保存之前的键值对
                result[item['key'].strip()] = item['value'].strip()
                item['key'] = ""
                item['value'] = ""

            # 切换到粗体状态
            state = 'key'
        else:
            # 切换到常规体状态
            state = 'value'

        # 根据当前状态添加文本
        item[state] += text

    # 处理最后一对键值
    if item['key'] and item['value']:
        result[item['key'].strip()] = item['value'].strip()

    return result
