import pdfplumber
from pdfplumber.page import Page
from pdfplumber.pdf import PDF
from pdfplumber._typing import T_obj_list

from ...utils.logger import get_logger

logger = get_logger("extra_shipserv")


def process_shipserv_order_pdf(pdf_path: str) -> dict:
    try:
        code = None

        with pdfplumber.open(pdf_path) as pdf:
            try:
                for page in pdf.pages:
                    result = page.search(
                        r'QS[TP]\d{9,10}[A-Z]{3}', return_chars=False)
                    if result[0]:
                        code = result[0]['text']
                        break
            except Exception as e:
                logger.error(
                    f"Error processing {pdf_path}: {e}")

    except Exception as e:
        logger.error(f"Error opening PDF {pdf_path}: {e}")
        return None

    return {
        'code': code
    }


def process_shipserv_pdf(pdf_path: str) -> dict:
    """
    处理PDF文件，提取表格数据。

    Args:
        pdf_path (str): PDF文件的路径。
    Returns:
        dict: 返回一个字典，包含以下键：
            - 'table_data': list[list[list[str]]] - 表格数据，每个section对应一张表
            - 'section_data': list[dict] - "section"部分的键值对数据
            - 'meta_data': list[dict] - 附件元数据的键值对数据
    """

    try:
        meta_data = {}
        table_data = []
        section_data = []

        with pdfplumber.open(pdf_path) as pdf:
            try:
                # 获取表格数据
                table_data = extract_table_data(pdf)

                # 提取"section"部分的数据
                section_data = extract_section_data(pdf, table_data)

                # 提取元数据中"subject"部分的数据，并更新元数据
                subject_data = extract_subject_data(pdf)
                meta_data.update(subject_data)

            except Exception as e:
                logger.error(
                    f"Error processing {pdf_path}: {e}")

    except Exception as e:
        logger.error(f"Error opening PDF {pdf_path}: {e}")
        return None

    return {
        'meta_data': meta_data,
        'table_data': table_data,
        'section_data': section_data,
    }


def extract_subject_data(pdf: PDF) -> dict:
    """
    从页面中提取"subject"部分的键值对数据。

    Args:
        pdf (PDF): PDF对象。
    Returns:
        dict: 返回"subject"部分的键值对字典。如果未找到，则返回空字典。
    """
    try:
        for page in pdf.pages:
            # subject信息固定在页面左半侧，裁剪页面避免右半侧数据干扰
            cropped_page = page.crop((0, 0, page.width / 2, page.height))

            # 查询以'Subject:'开头的主题行，以及可能的由主题过长导致的后续行
            lines = cropped_page.extract_text_lines()
            subject_lines_start_index = -1
            subject_lines_end_index = -1
            for i, line in enumerate(lines):
                if line['text'].startswith("Subject:"):
                    subject_lines_start_index = i
                    break
            for i, line in enumerate(lines[(subject_lines_start_index+1):]):
                # 后续行的字体都是常规体
                if "Regular" not in line['chars'][0]['fontname']:
                    subject_lines_end_index = i + 1 + subject_lines_start_index
                    break

            if subject_lines_start_index == -1 or subject_lines_end_index == -1:
                continue
            subject_lines = lines[subject_lines_start_index:subject_lines_end_index]

            return extract_dict_from_lines_by_font(page, subject_lines)

        return {}
    except Exception as e:
        logger.error(f"Error extracting subject: {e}")
        return {}


def extract_section_data(pdf: PDF, table_data: list[list[list[str]]]) -> list[dict]:
    """
    从页面中提取"section"部分的键值对数据。

    Args:
        pdf (PDF): PDF对象。
        table_results (list[list[list[str]]]): 表格数据。
    Returns:
        list[dict]: 返回一个"section"部分的键值对数据的字典列表。
    """

    try:
        # 每张表的第一个单元格为section信息
        section_cells = [table[0][0] for table in table_data]
        # 保留原本顺序并去重
        section_cells = list(dict.fromkeys(section_cells))
        if not section_cells:
            return []

        # 提取页面中的文本行
        lines = []
        for (pageIndex, page) in enumerate(pdf.pages):
            for line in page.extract_text_lines():
                lines.append((line, pageIndex))

        dicts = []
        for cell in section_cells:
            # 查找与单元格内容匹配的文本行
            # 这里单元格内容是以换行符分隔的
            section_lines_text = cell.split('\n')

            section_lines = []
            pageIndex = None
            for text in section_lines_text:
                for (line, pIndex) in lines:
                    if line['text'] == text:
                        pageIndex = pIndex
                        section_lines.append(line)
                        break

            # 如果没有找到匹配的文本行，则警告并跳过
            if not section_lines:
                logger.warning(
                    f"No matching section lines found for '{cell}'.")
                continue

            # 提取与单元格内容匹配的文本行的字典
            section_dict = extract_dict_from_lines_by_font(
                pdf.pages[pageIndex], section_lines)
            dicts.append(section_dict)

        return dicts
    except Exception as e:
        logger.error(f"Error extracting sections: {e}")
        return []


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
        section_result = None

        for page in pdf.pages:
            for table in page.extract_tables():
                firtst_cell = table[0][0]

                # 新的section
                if firtst_cell.startswith('Equipment Section'):
                    # 将之前的表添加到返回结果中
                    if section_result:
                        results.append(section_result)

                    # 将当前table作为新的section_result
                    section_result = table

                # 以'#'开头的续表
                elif firtst_cell == '#':
                    # 将除去额外表头的剩余表格添加到section_result中
                    section_result.extend(table[1:])

                # 其他意外情况
                else:
                    logger.warn(f"Unrecognized table type.")

        # 将最后一张表添加到返回结果中
        if section_result:
            results.append(section_result)

        return results

    except Exception as e:
        logger.error(f"Error extracting tables: {e}")
        return []


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
        elif 'Regular' in font_name:
            # 切换到常规体状态
            state = 'value'
        else:
            # 如果不是粗体或常规体，跳过
            continue

        # 根据当前状态添加文本
        item[state] += text

    # 处理最后一对键值
    if item['key'] and item['value']:
        result[item['key'].strip()] = item['value'].strip()

    return result
