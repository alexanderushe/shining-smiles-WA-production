# Shining Smiles WhatsApp Bot 🎓

A WhatsApp-based chatbot for Shining Smiles Group of Schools, enabling parents and students to access school services instantly.

## 🌟 What This App Does
This application serves as an automated receptionist and administrative assistant on WhatsApp. It allows verified parents/students to:
*   **Get Gate Passes**: Generate digital gate passes for students to leave school premises.
*   **Check Balances**: View current fee balances.
*   **Request Statements**: Get detailed fee statements.
*   **Verify Identity**: Automatically links WhatsApp numbers to student accounts via the school's SMS (School Management System).

## ✅ What Works Currently
*   **WhatsApp Integration**: Full two-way communication using the WhatsApp Cloud API.
*   **User Verification**: Automatically identifies users based on their registered phone number.
*   **Gate Pass Generation**:
    *   Validates student eligibility (fees paid).
    *   Generates a secure gate pass with ID, photo (if available), and validity details.
    *   *Note: Currently sending text-based passes with verification links while PDF generation is being optimized.*
*   **External API Integration**: Connects to the school's central SMS database for real-time data.
*   **Deployment**: Automated Docker-based deployment to AWS Lambda.

## 🚀 How It Works
1.  **User sends a message** to the school's WhatsApp number.
2.  **WhatsApp Cloud API** forwards the message to our **AWS Lambda** webhook.
3.  **Lambda Function**:
    *   Verifies the user's phone number against the school database.
    *   Processes the request (e.g., "Get Gate Pass").
    *   Fetches data from the **School Management System API**.
    *   Generates the response (text/media).
4.  **Response** is sent back to the user on WhatsApp.

## 🛠️ Deployment
We use a **Docker-based deployment workflow** to ensure compatibility with AWS Lambda's Linux environment (especially for Python dependencies like `fpdf2`, `Pillow`, `sqlalchemy`).

### **Deploying Updates**
To update the code on AWS Lambda, run the following script from the project root:

```bash
./docker-deploy.sh
```

**What this script does:**
1.  **Builds** a Docker container mimicking the AWS Lambda environment.
2.  **Installs** all Python dependencies (defined in the script) into a local package directory.
3.  **Zips** the application code and dependencies together.
4.  **Uploads** the zip file to the AWS Lambda function (`shining-smiles-bot`).
5.  **Verifies** the deployment.

---
*For detailed technical architecture and API documentation, see [TECHNICAL_DOCS.md](TECHNICAL_DOCS.md).*
