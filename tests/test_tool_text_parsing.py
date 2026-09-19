from src.agent.tool_defense import (
    _looks_like_tool_call, _normalize_tool_content, _parse_text_tool_calls,
    to_fake_tool_calls,
)


def test_detect_xml_invoke():
    assert _looks_like_tool_call(
        '<invoke name="search_web"><parameter name="query">x</parameter></invoke>')


def test_detect_openai_json():
    assert _looks_like_tool_call('{"name": "search_web", "arguments": {"query": "x"}}')


def test_detect_dsml():
    assert _looks_like_tool_call("<【DSML】tool_calls>")


def test_detect_dsml_fullwidth_variant():
    # 实测 DeepSeek 风格: 全角竖线控制令牌
    assert _looks_like_tool_call(
        "<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name=\"search_web\">")


def test_detect_bare_function_name():
    assert _looks_like_tool_call("search_bidding_knowledge(query='x')")


def test_detect_body_plus_tool_block():
    assert _looks_like_tool_call("这是回答。\n<tool_calls><invoke name=\"search_web\">...</invoke>")


def test_detect_clean_text():
    assert not _looks_like_tool_call("这是一个正常的回答")


def test_normalize_clears_tool_content():
    assert _normalize_tool_content('<invoke name="search_web">') == ""


def test_normalize_keeps_clean():
    assert _normalize_tool_content("正常内容") == "正常内容"


def test_parse_invoke():
    calls = _parse_text_tool_calls(
        '<invoke name="search_web"><parameter name="query">香港</parameter></invoke>')
    assert calls and calls[0]["name"] == "search_web"
    assert calls[0]["arguments"]["query"] == "香港"


def test_parse_json():
    calls = _parse_text_tool_calls('{"name": "search_web", "arguments": {"query": "x"}}')
    assert calls and calls[0]["name"] == "search_web"


def test_parse_no_tool():
    assert _parse_text_tool_calls("普通回答") is None


def test_parse_dsml_fullwidth_invoke():
    # 实测线上 payload 的全角竖线形态, 归一化后必须能解析出工具名与参数
    text = (
        "<｜｜DSML｜｜ calls>\n"
        "<｜｜DSML｜｜ invoke name=\"search_bidding_knowledge\">\n"
        "<｜｜DSML｜｜ parameter name=\"query\" string=\"true\">投标保证金比例 2%</｜｜DSML｜｜ parameter>\n"
        "</｜｜DSML｜｜ invoke>\n"
        "<｜｜DSML｜｜/calls>"
    )
    calls = _parse_text_tool_calls(text)
    assert calls and calls[0]["name"] == "search_bidding_knowledge"
    assert "2%" in calls[0]["arguments"]["query"]


def test_fake_tool_calls_structure():
    fakes = to_fake_tool_calls([{"name": "search_web", "arguments": {"query": "x"}}])
    assert fakes[0].function.name == "search_web"
    assert "x" in fakes[0].function.arguments
