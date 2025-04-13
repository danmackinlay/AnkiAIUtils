import warnings
import sys
import importlib.util
from pathlib import Path
from typing import List, Callable, Union, Dict, Tuple
import requests
import re
from bs4 import BeautifulSoup

from .shared import shared

REG_IMG = re.compile(
    r'<img .*?src=.*?/?>',
    flags=re.MULTILINE | re.DOTALL)

REG_SOUNDS = re.compile(
    r'\[sound:\w+\.\w{2,3}\]',
)
REG_LINKS = re.compile(
    r'[A-Za-z0-9]+://[A-Za-z0-9%-_]+(?:/[A-Za-z0-9%-_])*(?:#|\\?)[A-Za-z0-9%-_&=]*',
)

# source: https://stackoverflow.com/questions/6718633/python-regular-expression-again-match-url


def send_ntfy(url: str, title: str, content: str) -> None:
    """
    send notification to phone via ntfy.sh
    """
    assert "." in url and "/" in url, f"Invalid notification url: {url}"
    if not url.startswith("http"):
        url = "https://" + url
    requests.post(
        url,
        headers={
            "Title": title,
        },
        data=content.encode("utf8"),
    )


def load_formatting_funcs(
    func_names: List[str],
    path: str,
        ) -> List[Callable]:
    """
    load function defined in the python file located at path
    and returned them. Used to let the user specify formatting quircks.
    """
    ch = Path(path)
    filename = ch.stem
    assert ch.exists, f"string formatting file not found: {ch}"

    content = ch.read_text()
    assert content, f"empty string formatting file: {ch}"

    loaded = []

    for funcname in func_names:
        assert funcname not in globals(), f"{funcname} is already declared"
        spec = importlib.util.spec_from_file_location(
                f"{filename}.{funcname}",
                ch.absolute(),
        )
        modname = f"module_{funcname}"
        sys.modules[modname] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[modname])
        func = getattr(sys.modules[modname], funcname)
        loaded.append(func)
    return loaded


def replace_media(
    content: str,
    media: Union[None, Dict],
    mode: str,
    strict: bool = True,
    replace_image: bool = True,
    replace_links: bool = True,
    replace_sounds: bool = True,
) -> Tuple[str, Dict]:
    """
    Else: exclude any note that contains in the content:
        * an image (<img...)
        * or a sound [sound:...
        * or a link href / http
    This is because:
        1 as LLMs are non deterministic I preferred
            to avoid taking the risk of botching the content
        2 it costs less token

    The intended use is to call it first to replace
    each media by a simple string like [IMAGE_1] and check if it's
    indeed present in the output of the LLM then replace it back.

    It uses both bs4 and regex to be sure of itself
    """
    # ignore warnings from beautiful soup that can happen because anki is not exactly html
    warnings.filterwarnings("ignore", category=UserWarning, module='bs4')

    assert mode in ["add_media", "remove_media"]
    # If content is empty, return empty content and empty media dict
    if not content or not content.strip():
        return content, {}
    if media is None:
        media = {}
    assert isinstance(media, dict)
    assert any(rule for rule in [replace_sounds, replace_links, replace_image])

    red = shared.red

    if mode == "remove_media":
        assert not media
        images = []
        sounds = []
        links = []

        if replace_links:
            # fix links common issues
            content = content.replace(":// ", "://")
            content = content.replace("http ://", "http://")
            content = content.replace("https ://", "http://")

        # Images
        if replace_image and "<img" in content:
            soup = BeautifulSoup(content, 'html.parser')
            images_bs4 = [str(img) for img in soup.find_all('img')]
            # fix bs4 parsing as ending with /> instead of >
            images_bs4 = [
                img[:-2] + ">" if ((img not in content) and img[:-2] + ">" in content) else img
                for img in images_bs4
            ]
            images_reg = re.findall(REG_IMG, content)
            if len(images_bs4) != len(images_reg):
                if shared.verbose:
                    red(f"Different images found:\nbs4: {images_bs4}\nregex: {images_reg}\nContent: {content}")
                if images_bs4 and not images_reg:
                    images = [str(img) for img in images_bs4]
                elif (not images_bs4) and images_reg:
                    images = [str(img) for img in images_reg]
            else:
                images = [str(img) for img in images_bs4]
            try:
                assert images, f"no image found but should have. Text is '{content}'"
            except AssertionError as err:
                if strict:
                    raise
                red(err)
            for iimg, img in enumerate(images):
                try:
                    assert img in content, f"missing img from content:\nimg: {img}\ncontent: {content}"
                    assert re.search(REG_IMG, img), f"Regex couldn't identify img: {img}"
                    assert not re.search(REG_SOUNDS, img), f"Sound regex identifier img: {img}"
                except AssertionError as err:
                    if strict:
                        raise
                    red(err)
                    images[iimg] = None
            images = [i for i in images if i is not None]
            images = list(set(images))

        # Sounds
        if replace_sounds and "[sounds:" in content:
            sounds = re.findall(REG_SOUNDS, content)
            try:
                assert sounds, f"No sounds found but should have. Content: {content}"
            except AssertionError as err:
                if strict:
                    raise
                red(err)
            for isound, sound in enumerate(sounds):
                try:
                    assert sound in content, f"Sound is not in content: {sound}"
                    assert not re.search(REG_IMG, sound), f"Image regex identified this sound: {sound}"
                    assert re.search(REG_SOUNDS, sound), f"Regex didn't identify this sound: {sound}"
                except AssertionError as err:
                    if strict:
                        raise
                    red(err)
                    sounds[isound] = None
            sounds = [s for s in sounds if s is not None]
            sounds = list(set(sounds))

        # links
        if replace_links and "://" in content:
            links = re.findall(REG_LINKS, content)
            links = [
                link
                for link in links
                if not any(
                    other != link
                    and
                    other in link
                    for other in links
                )
            ]
            if strict:
                assert links, "No links found"
            for ilink, link in enumerate(links):
                try:
                    assert link in content, f"Link not in content:\nlink: {link}\ncontent: {content}"
                    assert re.search(REG_LINKS, link), f"Regex couldn't identify link: {link}"
                except AssertionError as err:
                    if strict:
                        raise
                    red(err)
                    links[ilink] = None
            links = [li for li in links if li is not None]
            links = list(set(links))

        if not images + sounds + links:
            return content, {}

        new_content = content

        # do the replacing
        for i, img in enumerate(images):
            assert replace_image, replace_image
            try:
                assert img in content, f"img '{img}' not in content '{content}'"
                assert img in new_content, f"img '{img}' not in new_content '{new_content}'"
                assert img not in media.keys() and img not in media.values()
                replaced = f"[IMAGE_{i+1}]"
                assert replaced not in media.keys() and replaced not in media.values()
                assert replaced not in content, f"Replaced '{replaced}' already in content '{content}'"
                assert replaced not in new_content, f"Replaced '{replaced}' already in new_content '{new_content}'"
                new_content = new_content.replace(img, replaced)
                media[replaced] = img
                assert img not in new_content
                assert replaced in new_content
            except AssertionError as err:
                if strict:
                    raise
                red(f"Failed assert when replacing image: '{err}'")
                continue

        for i, sound in enumerate(sounds):
            try:
                assert replace_sounds
                assert sound in content
                assert sound in new_content
                assert sound not in media.keys() and sound not in media.values()
                replaced = f"[SOUND_{i+1}]"
                assert replaced not in media.keys() and replaced not in media.values()
                assert replaced not in content
                assert replaced not in new_content
                new_content = new_content.replace(sound, replaced)
                media[replaced] = sound
                assert sound not in new_content
                assert replaced in new_content
            except AssertionError as err:
                if strict:
                    raise
                red(f"Failed assert when replacing sounds: '{err}'")
                continue

        for i, link in enumerate(links):
            try:
                assert replace_links
                assert link in content
                assert link not in media.keys()
                replaced = f"[LINK_{i+1}]"
                assert replaced not in media.keys() and replaced not in media.values()
                assert replaced not in content
                assert replaced not in new_content
                assert link in new_content or len(
                    [
                        val for val in media.values()
                        if link in val
                    ]
                )
                if link not in new_content:
                    continue
                else:
                    new_content = new_content.replace(link, replaced)
                    media[replaced] = link
                    assert link not in new_content
                    assert replaced in new_content
            except AssertionError as err:
                if strict:
                    raise
                red(f"Failed assert when replacing links: '{err}'")
                continue

        # check no media can be found anymore
        if replace_image:
            if strict:
                assert not re.findall(REG_IMG, new_content), new_content
                assert not BeautifulSoup(
                    new_content, 'html.parser').find_all('img'), new_content
                assert "<img" not in new_content, new_content
            elif "<img" in new_content:
                red(f"AnkiMediaReplacer: Found '<img' in '{new_content}'")
        if replace_sounds:
            if strict:
                assert not re.findall(REG_SOUNDS, new_content), new_content
                assert "[sound:" not in new_content, new_content
            elif "[sound:" in new_content:
                red(f"AnkiMediaReplacer: Found '[sound:' in '{new_content}'")
        if replace_links:
            if strict:
                assert not re.findall(REG_LINKS, new_content), new_content
                assert "://" not in new_content, new_content
            elif "://" in new_content:
                red(f"AnkiMediaReplacer: Found '://' in '{new_content}'")

        # check non empty
        temp = new_content
        for med, val in media.items():
            temp = temp.replace(med, "")
        assert temp.strip()

        # recursive check:
        assert replace_media(
            content=new_content,
            media=media,
            mode="add_media",
            strict=strict,
            replace_image=replace_image,
            replace_links=replace_links,
            replace_sounds=replace_sounds,
        )[0] == content

        return new_content, media

    elif mode == "add_media":
        assert media

        # TODO check that all media are found
        new_content = content
        for med, val in media.items():
            assert med in content
            assert val not in content
            assert val not in new_content
            new_content = new_content.replace(med, val)
            assert med not in new_content
            assert val in new_content

        return new_content, {}

    else:
        raise ValueError(mode)


