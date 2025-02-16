import argparse
import filecmp
import os
from pathlib import Path
from unittest.mock import Mock
import pytest
from collections import namedtuple
from typing import Callable, Text

from _pytest.monkeypatch import MonkeyPatch
from _pytest.pytester import RunResult
from rasa.cli import data
from rasa.shared.importers.importer import TrainingDataImporter
from rasa.validator import Validator


def test_data_split_nlu(run_in_simple_project: Callable[..., RunResult]):
    run_in_simple_project(
        "data", "split", "nlu", "-u", "data/nlu.yml", "--training-fraction", "0.75"
    )

    assert os.path.exists("train_test_split")
    # TODO: Comment back in as soon as NLU YAML writer is merged
    # https://github.com/RasaHQ/rasa/issues/6363
    # assert os.path.exists(os.path.join("train_test_split", "test_data.md"))
    # assert os.path.exists(os.path.join("train_test_split", "training_data.md"))


def test_data_convert_nlu(run_in_simple_project: Callable[..., RunResult]):
    run_in_simple_project(
        "data",
        "convert",
        "nlu",
        "--data",
        "data/nlu.yml",
        "--out",
        "out_nlu_data.json",
        "-f",
        "json",
    )

    assert os.path.exists("out_nlu_data.json")


def test_data_split_help(run: Callable[..., RunResult]):
    output = run("data", "split", "nlu", "--help")

    help_text = """usage: rasa data split nlu [-h] [-v] [-vv] [--quiet] [-u NLU]
                           [--training-fraction TRAINING_FRACTION]
                           [--random-seed RANDOM_SEED] [--out OUT]"""

    lines = help_text.split("\n")

    for i, line in enumerate(lines):
        assert output.outlines[i] == line


def test_data_convert_help(run: Callable[..., RunResult]):
    output = run("data", "convert", "nlu", "--help")

    help_text = """usage: rasa data convert nlu [-h] [-v] [-vv] [--quiet] -f {json,md,yaml}
                             --data DATA --out OUT [-l LANGUAGE]"""

    lines = help_text.split("\n")

    for i, line in enumerate(lines):
        assert output.outlines[i] == line


def test_data_validate_help(run: Callable[..., RunResult]):
    output = run("data", "validate", "--help")

    help_text = """usage: rasa data validate [-h] [-v] [-vv] [--quiet]
                          [--max-history MAX_HISTORY] [--fail-on-warnings]"""

    lines = help_text.split("\n")

    for i, line in enumerate(lines):
        assert output.outlines[i] == line


def _text_is_part_of_output_error(text: Text, output: RunResult) -> bool:
    found_info_string = False
    for line in output.errlines:
        if text in line:
            found_info_string = True
    return found_info_string


def test_data_validate_stories_with_max_history_zero(monkeypatch: MonkeyPatch):
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(help="Rasa commands")
    data.add_subparser(subparsers, parents=[])

    args = parser.parse_args(["data", "validate", "stories", "--max-history", 0])

    async def mock_from_importer(importer: TrainingDataImporter) -> Validator:
        return Mock()

    monkeypatch.setattr("rasa.validator.Validator.from_importer", mock_from_importer)

    with pytest.raises(argparse.ArgumentTypeError):
        data.validate_files(args)


def test_validate_files_exit_early():
    with pytest.raises(SystemExit) as pytest_e:
        args = {
            "domain": "data/test_domains/duplicate_intents.yml",
            "data": None,
            "max_history": None,
        }
        data.validate_files(namedtuple("Args", args.keys())(*args.values()))

    assert pytest_e.type == SystemExit
    assert pytest_e.value.code == 1


def test_rasa_data_convert_nlu_to_yaml(
    run_in_simple_project: Callable[..., RunResult], run: Callable[..., RunResult]
):
    converted_data_folder = "converted_data"
    os.mkdir(converted_data_folder)

    converted_single_file_folder = "converted_single_file"
    os.mkdir(converted_single_file_folder)

    simple_nlu_md = """
    ## intent:greet
    - hey
    - hello
    """

    os.mkdir("data/nlu")
    with open("data/nlu/nlu.md", "w") as f:
        f.write(simple_nlu_md)

    run_in_simple_project(
        "data",
        "convert",
        "nlu",
        "-f",
        "yaml",
        "--data",
        "data",
        "--out",
        converted_data_folder,
    )

    run_in_simple_project(
        "data",
        "convert",
        "nlu",
        "-f",
        "yaml",
        "--data",
        "data/nlu/nlu.md",
        "--out",
        converted_single_file_folder,
    )

    assert filecmp.cmp(
        Path(converted_data_folder) / "nlu_converted.yml",
        Path(converted_single_file_folder) / "nlu_converted.yml",
    )


def test_rasa_data_convert_stories_to_yaml(
    run_in_simple_project: Callable[..., RunResult], run: Callable[..., RunResult]
):
    converted_data_folder = "converted_data"
    os.mkdir(converted_data_folder)

    converted_single_file_folder = "converted_single_file"
    os.mkdir(converted_single_file_folder)

    simple_story_md = """
    ## happy path
    * greet OR goodbye
        - utter_greet
        - form{"name": null}
    """

    with open("data/stories.md", "w") as f:
        f.write(simple_story_md)

    run_in_simple_project(
        "data",
        "convert",
        "core",
        "-f",
        "yaml",
        "--data",
        "data",
        "--out",
        converted_data_folder,
    )

    run_in_simple_project(
        "data",
        "convert",
        "core",
        "-f",
        "yaml",
        "--data",
        "data/stories.md",
        "--out",
        converted_single_file_folder,
    )

    assert filecmp.cmp(
        Path(converted_data_folder) / "stories_converted.yml",
        Path(converted_single_file_folder) / "stories_converted.yml",
    )


def test_rasa_data_convert_nlg_to_yaml(
    run_in_simple_project: Callable[..., RunResult], run: Callable[..., RunResult]
):
    converted_data_folder = "converted_data"
    os.mkdir(converted_data_folder)

    converted_single_file_folder = "converted_single_file"
    os.mkdir(converted_single_file_folder)

    simple_nlg_md = (
        "## ask name\n"
        "* chitchat/ask_name\n"
        "- my name is Sara, Rasa's documentation bot!\n"
    )

    with open("data/responses.md", "w") as f:
        f.write(simple_nlg_md)

    run_in_simple_project(
        "data",
        "convert",
        "nlg",
        "-f",
        "yaml",
        "--data",
        "data",
        "--out",
        converted_data_folder,
    )

    run_in_simple_project(
        "data",
        "convert",
        "nlg",
        "-f",
        "yaml",
        "--data",
        "data/responses.md",
        "--out",
        converted_single_file_folder,
    )

    assert filecmp.cmp(
        Path(converted_data_folder) / "responses_converted.yml",
        Path(converted_single_file_folder) / "responses_converted.yml",
    )


def test_rasa_data_convert_nlu_lookup_tables_to_yaml(
    run_in_simple_project: Callable[..., RunResult], run: Callable[..., RunResult]
):
    converted_data_folder = "converted_data"
    os.mkdir(converted_data_folder)

    simple_nlu_md = """
    ## lookup:products.txt
      data/nlu/lookups/products.txt
    """

    os.mkdir("data/nlu")
    with open("data/nlu/nlu.md", "w") as f:
        f.write(simple_nlu_md)

    simple_lookup_table_txt = "core\n nlu\n x\n"
    os.mkdir("data/nlu/lookups")
    with open("data/nlu/lookups/products.txt", "w") as f:
        f.write(simple_lookup_table_txt)

    run_in_simple_project(
        "data",
        "convert",
        "nlu",
        "-f",
        "yaml",
        "--data",
        "data",
        "--out",
        converted_data_folder,
    )

    assert len(os.listdir(converted_data_folder)) == 1
