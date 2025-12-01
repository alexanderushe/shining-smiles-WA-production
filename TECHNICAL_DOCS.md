# Technical Documentation 🔧

## 🏗️ Architecture

*   **Runtime**: Python 3.11 on AWS Lambda
*   **Trigger**: API Gateway (Webhook for WhatsApp Cloud API)
*   **Database**: PostgreSQL (AWS RDS) - accessed via `sqlalchemy` + `pg8000`
*   **External Integrations**:
    *   **WhatsApp Cloud API**: For messaging.
    *   **School SMS API**: For student/finance data.
    *   **AWS Secrets Manager**: For secure database credentials.
    *   **AWS S3**: For storing generated documents (PDFs/images).

## 🔌 External APIs (School SMS)

The bot interacts with the School Management System via the following endpoints (Base URL: `http://31.187.76.42/api/`):

### **1. Student Billed Fees**
*   **Endpoint**: `/student/billed-fee-types/`
*   **Method**: `GET`
*   **Purpose**: Retrieves the fee structure and billed amounts for a student.
*   **Parameters**: `student_id_number`, `term`

### **2. Student Payments**
*   **Endpoint**: `/student/payments/`
*   **Method**: `GET`
*   **Purpose**: Retrieves payment history to calculate outstanding balance.
*   **Parameters**: `student_id_number`, `term`

### **3. Student Profile (Implied)**
*   **Purpose**: Verifies phone numbers and links them to student IDs.

## 📦 Dependency Management

We use a custom **Docker-based build process** because AWS Lambda runs on Amazon Linux, and some Python libraries (like `Pillow`, `cryptography`) require OS-specific C extensions.

### **Key Dependencies**
*   `requests`: API communication.
*   `sqlalchemy` + `pg8000`: Database ORM and driver (pure Python driver preferred for Lambda).
*   `fpdf2`: PDF generation (Pure Python).
*   `Pillow`: Image processing (required by fpdf2 for images).
*   `segno`: QR code generation (Pure Python).
*   `boto3`: AWS SDK (pre-installed on Lambda, but good to track).

### **The Deployment Script (`./docker-deploy.sh`)**
This script is the source of truth for deployments. It performs the following steps:

1.  **Cleanup**: Removes old build artifacts (`docker-package`, `lambda_function.zip`).
2.  **Docker Build**: Runs a container using `public.ecr.aws/sam/build-python3.11`.
    *   This ensures binaries are compiled for the exact OS Lambda uses.
3.  **Pip Install**: Installs requirements into the `docker-package` folder inside the container.
    *   *Note*: We specifically pin versions like `Pillow==10.0.0` for stability.
4.  **Packaging**:
    *   Copies application code (`src/`).
    *   Zips everything into `lambda_function.zip`.
5.  **Deploy**: Uses `aws lambda update-function-code` to push the zip.

## 🔍 Troubleshooting & Logs

*   **CloudWatch Logs**: All application logs (INFO, ERROR, DEBUG) are streamed to AWS CloudWatch.
*   **Common Issues**:
    *   **Timeouts**: If the SMS API is slow, the Lambda might time out. We have set a **10s timeout** on external API calls to fail fast.
    *   **Dependency Errors**: `ImportError` usually means a binary mismatch. Always use `./docker-deploy.sh` to rebuild.

## 🔮 Future Roadmap
*   **PDF Gate Passes**: Re-enabling full PDF generation once dependency issues are fully resolved.
*   **Progress Reports**: Integration with grading system (See `PROGRESS_REPORTS_PLAN.md`).
*   **Attendance Alerts**: Proactive notifications for parents.
