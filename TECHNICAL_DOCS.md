# Technical Documentation 🔧

## 🏗️ Architecture

*   **Runtime**: Python 3.11 on AWS Lambda
*   **Trigger**: 
    *   API Gateway (Webhook for WhatsApp Cloud API)
    *   AWS EventBridge (Scheduled Cron Jobs)
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

## 🤖 Automation & Scheduling
We use **AWS EventBridge** to handle scheduled background tasks. This allows the bot to be proactive rather than just reactive.

### **Scheduled Events**
The `template.yaml` defines the following schedules:
1.  **Daily Payment Check** (`06:00 UTC`): Checks for new payments and updates the database.
2.  **Weekly Reminders** (`Monday 07:00 UTC`): Sends balance reminders to parents.
3.  **Daily Profile Sync** (`00:00 UTC`): Syncs student data from the School SMS.

### **Scalable Profile Sync ("Smart Batching")**
To handle large datasets (1000+ students) without hitting AWS Lambda's 15-minute timeout, we implemented a **Recursive Lambda** pattern:
1.  **Time-Aware**: The sync function (`sync_student_profiles`) monitors its own execution time.
2.  **Graceful Stop**: If execution exceeds **12 minutes**, it stops processing and saves its state (current page).
3.  **Self-Invocation**: The Lambda function asynchronously invokes *itself* with the `start_page` parameter to resume exactly where it left off.
4.  **Result**: Infinite scalability for student records without timeout errors.

## 🎫 Gate Pass System

### **Overview**
The gate pass system allows parents to request digital passes for students to leave school premises. It incorporates multiple safeguards to ensure security and prevent resource abuse.

### **Core Components**

#### **1. PDF Generation (`gatepass_service.py`)**
- **Library**: `fpdf2` (pure Python, no C dependencies)
- **QR Codes**: Generated using `segno` library
- **Storage**: PDFs uploaded to S3 bucket (`shining-smiles-gatepasses`)
- **Delivery**: Sent via WhatsApp Cloud API with presigned URLs (1-hour expiry)

#### **2. QR Code Verification**
- **Endpoint**: `GET /verify-gatepass?pass_id=<UUID>&whatsapp_number=<NUMBER>`
- **Route**: Configured in API Gateway, handled by Lambda
- **Template Engine**: Jinja2 (standalone, no Flask context required)
- **Security**: Tracks scan attempts in `gate_pass_scans` table
- **Warning System**: Alerts if scanned by unauthorized number

#### **3. Rate Limiting (Tiered Access Control)**
- **Database**: `gate_pass_request_logs` table tracks weekly requests per student
- **Reset Logic**: Automatic weekly reset every Monday
- **Tiers**:
  - **Tier 1 (1-3 requests)**: Send full PDF via WhatsApp
  - **Tier 2 (4-5 requests)**: Send text-only details (no PDF)
  - **Tier 3 (6+ requests)**: Block with 429 status code
- **Cost Savings**: Reduces WhatsApp media message costs and S3 bandwidth

#### **4. Term Restrictions**
- **Configuration**: Term dates defined in `config.py`
  - `TERM_START_DATES`: Beginning of each term
  - `TERM_END_DATES`: End of each term
- **Validation**: Gate passes only issued if current date is within active term
- **User Message**: If term ended, bot informs user of next term start date

#### **5. Dynamic Expiry Calculation**
Gate pass validity is calculated based on payment percentage:
```python
if payment_percentage >= 100:
    expiry = term_end_date
elif payment_percentage >= 70:
    expiry = term_end_date - 30 days
elif payment_percentage >= 50:
    expiry = end_of_current_month
else:
    # No gate pass issued
```

### **Database Schema**

#### **gate_passes**
| Column | Type | Description |
|:---|:---|:---|
| `id` | Integer | Primary key |
| `student_id` | String | Foreign key to student_contacts |
| `pass_id` | String (UUID) | Unique pass identifier |
| `issued_date` | DateTime | When pass was created |
| `expiry_date` | DateTime | When pass becomes invalid |
| `payment_percentage` | Integer | Fee payment % at time of issue |
| `whatsapp_number` | String | Authorized phone number |
| `pdf_path` | String | S3 key for PDF file |

#### **gate_pass_scans**
| Column | Type | Description |
|:---|:---|:---|
| `id` | Integer | Primary key |
| `pass_id` | String | Reference to gate pass |
| `scanned_at` | DateTime | Scan timestamp |
| `scanned_by_number` | String | Phone number that scanned |
| `matched_registered_number` | Boolean | Security flag |

#### **gate_pass_request_logs**
| Column | Type | Description |
|:---|:---|:---|
| `id` | Integer | Primary key |
| `student_id` | String | Student identifier |
| `week_start_date` | DateTime | Monday of current week |
| `request_count` | Integer | Number of requests this week |
| `last_request_date` | DateTime | Most recent request |

### **API Gateway Configuration**
- **Route**: `GET /verify-gatepass`
- **Integration**: Lambda proxy integration to `shining-smiles-whatsapp`
- **Permissions**: API Gateway has invoke permission for Lambda
- **Response**: Returns HTML page rendered by Jinja2

## 🔮 Future Roadmap
*   **Progress Reports**: Integration with grading system (See `PROGRESS_REPORTS_PLAN.md`).
*   **Attendance Alerts**: Proactive notifications for parents.
