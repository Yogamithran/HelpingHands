 HelpingHands – Volunteer & Donation Coordination Portal

HelpingHands is a simple web-based platform designed to connect NGOs, volunteers and donors in one place. It helps NGOs organize social activities, volunteers discover opportunities and donors contribute essential resources.

 Project Overview

The main objective of HelpingHands is to simplify volunteer participation and donation coordination through a centralized web application.

 Features

- User Registration and Login
- Role-Based User Access
- Volunteer Dashboard
- NGO Dashboard
- Create and Manage Activities
- Browse and Search Activities
- Volunteer Join Requests
- Approve or Reject Participation Requests
- Donation Submission and Tracking
- Admin Dashboard

 Technology Stack

| Technology | Purpose |
|---|---|
| HTML | Structure |
| CSS | Styling |
| JavaScript | Frontend functionality |
| Bootstrap 5 | Responsive Design |
| Python Flask | Backend |
| SQLite | Database |

 Team Members

| Member | Name | Responsibility |
|---|---|---|
| Member 1 | Udhayan | Frontend Development |
| Member 2 | Deepasri | Volunteer Module |
| Member 3 | Dhivys | NGO & Donation Module |
| Member 4 | Yogamithran | Backend & Admin Module |

 Project Structure

```text
HelpingHands/
│
├── app.py
├── database.py
├── requirements.txt
├── README.md
│
├── database/
├── templates/
│   ├── base.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── activities.html
│   ├── donations.html
│   ├── volunteer/
│   ├── ngo/
│   └── admin/
│
└── static/
    ├── css/
    ├── js/
    └── images/
```

 Installation and Setup

1. Clone the repository:

```bash
git clone https://github.com/Yogamithran/HelpingHands.git
```

2. Navigate to the project folder:

```bash
cd HelpingHands
```

3. Create a virtual environment:

```bash
python -m venv venv
```

4. Activate the environment:

```bash
venv\Scripts\activate
```

5. Install dependencies:

```bash
pip install -r requirements.txt
```

6. Run the application:

```bash
python app.py
```

7. Open the local URL displayed in the terminal.

 Git Workflow

The project follows a feature-branch workflow.

- `main` – Main project branch.
- `develop` – Development integration branch.
- `feature/udhayan` – Frontend development.
- `feature/deepasri` – Volunteer module.
- `feature/dhivys` – NGO and donation module.
- `feature/yogamithran` – Backend and admin module.

All feature branches should submit Pull Requests to the `develop` branch.

 Project Goal

To develop a simple and user-friendly platform that improves coordination between NGOs, volunteers and donors.
