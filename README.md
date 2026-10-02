## 🌐 Live Demo

🚀 **Try DeadlineAI:**  
https://deadlinetracker-ajibw7uwt2hsnt9cuqmdc4.streamlit.app/

# DeadlineAI

DeadlineAI turns academic documents into a source-grounded list of deadlines. Upload a syllabus, timetable, assignment sheet, exam schedule, college notice, or project schedule as a JPG, JPEG, PNG, or PDF. Gemini Vision extracts tasks and dates; students can review source evidence, ask follow-up questions, and email themselves a concise digest.

## Features

- Student name and email onboarding
- Image preview and PDF upload support
- Gemini Vision extraction with explicit handling for unclear or missing dates
- Deadline list with source evidence
- Follow-up chat grounded in the extracted data
- Gemini-generated email digest sent through Gmail SMTP
- Credentials read from Streamlit Secrets, never hard-coded

## Requirements

- Python 3.10 or newer
- A Gemini API key
- Gmail with two-step verification and a Gmail app password to enable email sending

## Run locally

1. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Edit `.streamlit/secrets.toml` and add your credentials:

   ```toml
   GEMINI_API_KEY = "your-gemini-api-key"
   GMAIL_ADDRESS = "your-gmail-address@gmail.com"
   GMAIL_APP_PASSWORD = "your-gmail-app-password"
   ```

   `.streamlit/secrets.toml` is excluded from Git. The committed `.streamlit/secrets.toml.example` contains placeholders only.

4. Start the app:

   ```powershell
   streamlit run app.py
   ```

Deadline extraction and chat need `GEMINI_API_KEY`. Email additionally needs `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD`. Gmail app passwords are created in Google Account security settings after two-step verification is enabled; do not use your regular Gmail password.


## Deploy on Streamlit Community Cloud

1. Push this project to a GitHub repository. Do not add `.streamlit/secrets.toml`, `.venv/`, or `venv/`.
2. In Streamlit Community Cloud, create an app from the repository and set the main file path to `app.py`.
3. Open the deployed app's **Settings → Secrets** and add:

   ```toml
   GEMINI_API_KEY = "your-gemini-api-key"
   GMAIL_ADDRESS = "your-gmail-address@gmail.com"
   GMAIL_APP_PASSWORD = "your-gmail-app-password"
   ```

4. Save the secrets and reboot the app.

## Accuracy and privacy notes

The extraction prompt asks Gemini to include short document evidence for each item and to leave dates blank when the document does not establish a complete, unambiguous date. The app marks those dates as unclear instead of guessing. Model extraction can still make mistakes, so verify important dates against the original document.

Uploaded documents are sent to Google Gemini for analysis. Student details and extracted deadlines are kept in Streamlit's session state for the current browser session; this demo does not provide a database or long-term account storage. Email is sent only after the student clicks the digest button.

## Project files

```text
Deadline_Tracker/
├── app.py
├── prompts.py
├── requirements.txt
├── README.md
├── .gitignore
└── .streamlit/
    ├── secrets.toml             # Local-only; ignored by Git
    └── secrets.toml.example     # Safe placeholder template
```
