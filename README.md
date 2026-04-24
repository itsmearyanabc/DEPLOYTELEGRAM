# Telegram Multi-Account Bulk Messenger (Elyndor Interactive Edition)

Professional automation tool for monitoring channels and bulk forwarding messages with multiple account rotation and anti-spam protection.

## 🚀 Key Features
-   **Web Admin Dashboard:** Manage everything from your browser.
-   **Bulk Account Support:** Use 20+ accounts with a single API ID/Hash.
-   **Official Forwarding:** Messages show the "Forwarded from..." tag.
-   **Anti-Spam Security:** Randomized 10-15 minute delays and round-robin rotation.
-   **Session Manager:** Easily clear and reset logins from the UI.

## 🛠️ Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch the Admin Panel
Run:
```bash
python app.py
```

### 3. Open the Dashboard
Go to: 👉 **http://localhost:5000**

### 4. Configuration
1.  Enter your **Global API ID** and **API Hash**.
2.  Paste your **list of Phone Numbers** (one per line).
3.  Enter the **Source Channel ID** (found in logs after clicking Start).
4.  Paste your **Target List** (usernames like @user1).
5.  Click **Save All Configuration**.

### 5. Start Automation
Click **"🚀 Start Automation"**. 
*Note: For first-time setup, new terminal windows will appear for each phone number. Enter the Telegram Login Code in each window.*

---

## 🔒 License Notice
This is a **Trial Version** restricted to **5 messages** for validation purposes. 
**Contact Elyndor Interactive for the full, unlimited license.**
