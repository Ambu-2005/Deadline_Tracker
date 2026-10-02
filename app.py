"""DeadlineAI: extract, review, and share academic deadlines."""

from __future__ import annotations
import time
import hashlib
from datetime import date
from html import escape
import json
import re
import smtplib
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

import streamlit as st
from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

from prompts import (
    CHAT_PROMPT,
    SUMMARY_REQUEST_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)


MODEL_NAME = "gemini-2.5-flash"
SUPPORTED_TYPES = ["jpg", "jpeg", "png", "pdf"]
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

st.set_page_config(
    page_title="DeadlineAI | Academic planner",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
    :root {
        --ink: #17252b;
        --muted: #64757a;
        --paper: #f5f7f3;
        --surface: #ffffff;
        --line: #dce4df;
        --teal: #087e78;
        --teal-soft: #e3f3ef;
        --coral: #c65e43;
    }
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; color: var(--ink); }
    .stApp { background: var(--paper); }
    h1, h2, h3 { font-family: 'Manrope', sans-serif !important; letter-spacing: 0 !important; }
    h1 { font-size: 2.15rem !important; font-weight: 800 !important; }
    [data-testid="stSidebar"] { background: #edf2ec; border-right: 1px solid var(--line); }
    [data-testid="stSidebar"] h2 { font-size: 1.05rem; }
    .brandline { color: var(--teal); font-size: .78rem; font-weight: 700; text-transform: uppercase; }
    .subtitle { color: var(--muted); margin-top: -.7rem; }
    .section-label { color: var(--teal); font-size: .75rem; font-weight: 700; text-transform: uppercase; letter-spacing: .08em; }
    .deadline-card { background: var(--surface); border: 1px solid var(--line); border-left: 4px solid var(--teal); padding: 1rem 1.15rem; border-radius: 6px; margin: .6rem 0; }
    .deadline-card h3 { margin: 0 0 .35rem 0; font-size: 1.05rem; }
    .deadline-meta { color: var(--muted); font-size: .9rem; }
    .date-pill { display: inline-block; color: #075e59; background: var(--teal-soft); font-weight: 700; border-radius: 4px; padding: .25rem .55rem; font-size: .85rem; }
    .welcome-band { border-left: 4px solid var(--coral); background: #fff; padding: .9rem 1rem; border-radius: 4px; }
    div.stButton > button[kind="primary"] { background: var(--teal); border-color: var(--teal); }
    div.stButton > button { border-radius: 5px; }
    [data-testid="stFileUploader"] { background: #fff; border: 1px dashed #9ab5ab; border-radius: 6px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def get_secret(name: str) -> str:
    """Read a configured Streamlit secret without exposing its value."""
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value).strip()


def valid_email(address: str) -> bool:
    parsed_name, parsed_address = parseaddr(address)
    return bool(
        not parsed_name
        and parsed_address == address.strip()
        and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", parsed_address)
    )


def detect_upload_mime_type(upload: Any) -> str | None:
    """Identify supported uploads from their content instead of their filename."""
    payload = upload.getvalue()
    if payload.startswith(b"%PDF-"):
        return "application/pdf"
    try:
        with Image.open(upload) as image:
            image_format = image.format
            image.verify()
        if image_format == "JPEG":
            return "image/jpeg"
        if image_format == "PNG":
            return "image/png"
    except (UnidentifiedImageError, OSError, ValueError):
        return None
    finally:
        upload.seek(0)
    return None


def validate_upload(upload: Any) -> tuple[bool, str]:
    """Check upload content before sending it to the model."""
    if upload is None or not upload.getvalue():
        return False, "Choose a document with content before extracting deadlines."
    payload = upload.getvalue()
    if len(payload) > MAX_DOCUMENT_BYTES:
        return False, "This file is larger than 20 MB. Compress it or upload a smaller scan."
    if detect_upload_mime_type(upload) is None:
        return False, "Unsupported or unreadable file. Upload a valid JPG, JPEG, PNG, or PDF."
    return True, ""


def decode_json(response_text: str) -> dict[str, Any]:
    """Parse a JSON response, tolerating a surrounding Markdown code fence."""
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Gemini did not return a readable deadline list.")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict) or not isinstance(data.get("deadlines"), list):
        raise ValueError("Gemini returned an unexpected deadline format.")
    return data


def normalize_deadlines(data: dict[str, Any]) -> list[dict[str, str]]:
    """Keep only expected fields and reject entries without source evidence."""
    deadlines: list[dict[str, str]] = []
    for item in data["deadlines"]:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        evidence = str(item.get("source_evidence", "")).strip()
        if not evidence:
            continue
        status = str(item.get("date_status", "unclear")).lower().strip()
        if status not in {"confirmed", "unclear", "not_found"}:
            status = "unclear"
        due_date = str(item.get("due_date", "")).strip()
        try:
            parsed_date = date.fromisoformat(due_date)
            valid_date = parsed_date.isoformat() == due_date
        except ValueError:
            valid_date = False
        if status != "confirmed" or not valid_date:
            due_date = ""
            if status == "confirmed":
                status = "unclear"
        deadlines.append(
            {
                "task": task,
                "subject": str(item.get("subject", "")).strip(),
                "due_date": due_date,
                "date_text": str(item.get("date_text", "")).strip(),
                "date_status": status,
                "description": str(item.get("description", "")).strip(),
                "source_evidence": evidence,
            }
        )
    return deadlines


def extract_deadlines(upload: Any, api_key: str) -> tuple[list[dict[str, str]], str]:
    """Ask Gemini to extract source-grounded deadlines from an image or PDF."""

    mime_type = detect_upload_mime_type(upload)

    if mime_type is None:
        raise ValueError(
            "Unsupported or unreadable file. "
            "Upload a valid JPG, JPEG, PNG, or PDF."
        )

    client = genai.Client(api_key=api_key)

    max_attempts = 3

    for attempt in range(max_attempts):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    SYSTEM_PROMPT,
                    types.Part.from_bytes(
                        data=upload.getvalue(),
                        mime_type=mime_type,
                    ),
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )

            # Gemini request succeeded
            break

        except Exception as error:
            error_text = str(error)
            error_code = getattr(error, "code", None)

            # Detect temporary Gemini 503 / UNAVAILABLE errors
            is_503_error = (
                error_code == 503
                or "503" in error_text
                or "UNAVAILABLE" in error_text
            )

            # Retry temporary 503 errors
            if is_503_error and attempt < max_attempts - 1:
                wait_seconds = 2 ** attempt

                time.sleep(wait_seconds)

                continue

            # If it is another error, or all retries failed,
            # send the error to the existing error handler.
            raise

    if not response.text:
        raise ValueError(
            "Gemini returned an empty response. "
            "Try a clearer document."
        )

    data = decode_json(response.text)

    deadlines = normalize_deadlines(data)

    note = str(data.get("document_note", "")).strip()

    return deadlines, note


def deadline_context() -> str:
    entries = st.session_state.get("deadlines", [])
    return json.dumps(entries, ensure_ascii=False, indent=2)


def send_digest(recipient: str, student_name: str, digest: str) -> None:
    email_address = get_secret("GMAIL_ADDRESS")
    app_password = get_secret("GMAIL_APP_PASSWORD")
    if not email_address or not app_password:
        raise RuntimeError("Email sending is not configured yet. Add the Gmail secrets in Streamlit settings.")
    message = EmailMessage()
    message["Subject"] = "Your DeadlineAI academic deadline digest"
    message["From"] = email_address
    message["To"] = recipient
    message.set_content(f"Hi {student_name},\n\nHere is your academic deadline digest:\n\n{digest}\n\nSent by DeadlineAI.")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(email_address, app_password)
        smtp.send_message(message)


def render_deadline(item: dict[str, str], number: int) -> None:
    if item["date_status"] == "confirmed":
        date_label = date.fromisoformat(item["due_date"]).strftime("%d %B %Y").lstrip("0")
    elif item["date_status"] == "not_found":
        date_label = "No due date found"
    else:
        date_label = "Date unclear"
    task = escape(item["task"])
    subject = escape(item["subject"])
    description = escape(item["description"])
    date_text = escape(item["date_text"])
    st.markdown(
        f"""
        <div class="deadline-card">
          <div class="date-pill">{number:02d} · {date_label}</div>
          <h3>{task}</h3>
          <div class="deadline-meta">{('Subject: ' + subject) if subject else 'Subject not identified'}</div>
          {('<p>' + description + '</p>') if description else ''}
          {('<small>Document says: ' + date_text + '</small>') if date_text and item['date_status'] != 'confirmed' else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.markdown('<div class="brandline">Your academic year, in view</div>', unsafe_allow_html=True)
    st.title("📅 DeadlineAI")
    st.markdown('<p class="subtitle">AI-powered Academic Deadline Tracker</p>', unsafe_allow_html=True)

    with st.sidebar:
        st.markdown("## Student details")
        with st.form("student_details"):
            name = st.text_input("Your name", value=st.session_state.get("student_name", ""), placeholder="e.g. Alex Morgan")
            email = st.text_input("Email address", value=st.session_state.get("student_email", ""), placeholder="you@example.edu")
            saved = st.form_submit_button("Save details", use_container_width=True)
        if saved:
            if not name.strip():
                st.error("Please enter your name.")
            elif not valid_email(email):
                st.error("Enter a valid email address.")
            else:
                st.session_state.student_name = name.strip()
                st.session_state.student_email = email.strip()
                st.success("Student details saved.")
        st.caption("Your details stay in this browser session.")

    if st.session_state.get("student_name"):
        st.markdown(
            f'<div class="welcome-band">{escape(WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.student_name))}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<div class='section-label'>01 / Add a document</div>", unsafe_allow_html=True)
    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        upload = st.file_uploader(
            "Upload a document (JPG, JPEG, PNG, or PDF; max 20 MB)",
            help="Supported formats: JPG, JPEG, PNG, and PDF. Files are checked by their contents, so the extension is optional.",
        )
        if upload:
            valid, message = validate_upload(upload)
            if valid:
                file_hash = hashlib.sha256(upload.getvalue()).hexdigest()
                if st.session_state.get("active_upload_hash") != file_hash:
                    st.session_state.active_upload_hash = file_hash
                    st.session_state.pop("deadlines", None)
                    st.session_state.pop("document_note", None)
                    st.session_state.chat_messages = []
                if detect_upload_mime_type(upload).startswith("image/"):
                    st.image(upload, caption=upload.name, use_container_width=True)
                else:
                    st.info(f"PDF ready for analysis: **{upload.name}** · {len(upload.getvalue()) / 1024:.0f} KB")
            else:
                st.error(message)
        extract_clicked = st.button("Extract deadlines", type="primary", icon="🔎", use_container_width=True)

    with right:
        st.markdown("### What gets extracted")
        st.write("Assignments, projects, exams, events, due dates, subjects, and useful submission notes.")
        st.caption("Dates are shown as confirmed only when the document provides clear evidence.")

    if extract_clicked:
        if upload is None:
            st.error("Upload a document first.")
        else:
            valid, message = validate_upload(upload)
            if not valid:
                st.error(message)
            elif not get_secret("GEMINI_API_KEY"):
                st.error("Deadline extraction is not configured yet. Add GEMINI_API_KEY in Streamlit Secrets.")
            else:
                try:
                    with st.spinner("Reading your document and checking dates…"):
                        found, note = extract_deadlines(upload, get_secret("GEMINI_API_KEY"))
                    st.session_state.deadlines = found
                    st.session_state.document_note = note
                    st.session_state.active_upload_hash = hashlib.sha256(upload.getvalue()).hexdigest()
                    st.session_state.chat_messages = []
                except ValueError as error:
                    st.error(str(error))
                except Exception as error:
                    st.error(f"Gemini error: {error}")
                    st.exception(error)
    deadlines = sorted(
        st.session_state.get("deadlines", []),
        key=lambda item: (item["date_status"] != "confirmed", item["due_date"] or "9999-12-31"),
    )
    if "deadlines" in st.session_state:
        st.divider()
        st.markdown("<div class='section-label'>02 / Your deadlines</div>", unsafe_allow_html=True)
        st.subheader("Upcoming deadlines")
        if st.session_state.get("document_note"):
            st.info(st.session_state.document_note)
        if not deadlines:
            st.info("No deadlines were identified in this document. If you expected one, try a clearer image or a different page.")
        else:
            for index, item in enumerate(deadlines, start=1):
                render_deadline(item, index)
                with st.expander("Source evidence"):
                    st.write(item["source_evidence"])

        if deadlines:
            st.divider()
            st.markdown("<div class='section-label'>03 / Ask about your schedule</div>", unsafe_allow_html=True)
            for message in st.session_state.get("chat_messages", []):
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            question = st.chat_input("Ask about your extracted deadlines")
            if question:
                st.session_state.chat_messages.append({"role": "user", "content": question})
                with st.chat_message("user"):
                    st.markdown(question)
                if not get_secret("GEMINI_API_KEY"):
                    answer = "Chat is unavailable because GEMINI_API_KEY is not configured."
                else:
                    try:
                        with st.spinner("Checking your deadlines…"):
                            client = genai.Client(api_key=get_secret("GEMINI_API_KEY"))
                            chat_prompt = f"{CHAT_PROMPT}\n\nExtracted deadlines (JSON):\n{deadline_context()}\n\nStudent question: {question}"
                            response = client.models.generate_content(model=MODEL_NAME, contents=chat_prompt)
                            answer = response.text or "I couldn't form an answer from the extracted deadlines."
                    except Exception:
                        answer = "I couldn't reach Gemini just now. Please try your question again."
                st.session_state.chat_messages.append({"role": "assistant", "content": answer})
                with st.chat_message("assistant"):
                    st.markdown(answer)

        st.divider()
        st.markdown("<div class='section-label'>04 / Send yourself a digest</div>", unsafe_allow_html=True)
        if st.button("📧 Send Deadline Digest", use_container_width=True):
            recipient = st.session_state.get("student_email", "")
            if not recipient:
                st.error("Save your name and email address in the sidebar before sending a digest.")
            elif not get_secret("GEMINI_API_KEY"):
                st.error("Digest generation is not configured yet. Add GEMINI_API_KEY in Streamlit Secrets.")
            else:
                try:
                    with st.spinner("Preparing your digest…"):
                        client = genai.Client(api_key=get_secret("GEMINI_API_KEY"))
                        digest_response = client.models.generate_content(
                            model=MODEL_NAME,
                            contents=f"{SUMMARY_REQUEST_PROMPT}\n\nExtracted deadlines (JSON):\n{deadline_context()}",
                        )
                        digest = (digest_response.text or "").strip()
                        if not digest:
                            raise ValueError("Gemini returned an empty digest.")
                    with st.spinner("Sending your email…"):
                        send_digest(recipient, st.session_state.get("student_name", "student"), digest)
                    st.success(f"Deadline digest sent to {recipient}.")
                except RuntimeError as error:
                    st.error(str(error))
                except Exception:
                    st.error("The digest could not be generated or emailed. Check your Gemini and Gmail settings, then try again.")


if __name__ == "__main__":
    main()