# 📊 Progress Reports Implementation Plan

This document outlines the roadmap for implementing student progress reports via the WhatsApp chatbot.

## **Phase 1: Data Collection (Teacher Side)**

### **Option A: Existing SMS System Integration** ⭐ RECOMMENDED
*   **Workflow**: Teachers enter grades into the existing SMS database.
*   **Integration**: Create an API endpoint (`/api/student/grades/`) that the WhatsApp Bot can query.
*   **Advantages**:
    *   Teachers already use this system.
    *   No new training needed.
    *   Data is centralized.
    *   Minimal development effort.

### **Option B: New Teacher Web Portal**
*   **Workflow**: Build a simple web app for teachers to login and enter grades.
*   **Integration**: Store data in the existing database for the bot to access.

---

## **Phase 2: Database Schema**

Proposed schema additions to the existing database:

```sql
-- Grades Table
CREATE TABLE student_grades (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(20),  -- e.g., SSC20257279
    subject VARCHAR(100),    -- e.g., Mathematics
    term VARCHAR(10),        -- e.g., 2025-2
    assessment_type VARCHAR(50), -- Quiz, Mid-term, Final
    score DECIMAL(5,2),      -- e.g., 85.5
    max_score DECIMAL(5,2),  -- e.g., 100
    grade VARCHAR(5),        -- A, B, C
    teacher_comment TEXT,
    class_average DECIMAL(5,2),
    date_recorded TIMESTAMP,
    teacher_id VARCHAR(20)
);

-- Teacher Comments Table
CREATE TABLE teacher_comments (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(20),
    term VARCHAR(10),
    subject VARCHAR(100),
    comment TEXT,
    teacher_name VARCHAR(100),
    date_added TIMESTAMP
);
```

---

## **Phase 3: SMS API Endpoints**

New endpoints to be added to the SMS API:

### **1. Get Student Grades**
*   **Endpoint**: `GET /api/student/grades/`
*   **Params**:
    *   `student_id_number`: "SSC20257279"
    *   `term`: "2025-2"
*   **Response**:
    ```json
    {
        "student": "[SSC20257279] PEACE KUWAZA",
        "term": "Term 2 - 2025",
        "grades": [
            {
                "subject": "Mathematics",
                "assessments": [
                    {"type": "Quiz 1", "score": 18, "max": 20, "date": "2025-05-15"},
                    {"type": "Mid-term", "score": 75, "max": 100, "date": "2025-06-20"}
                ],
                "average": 85.5,
                "grade": "A",
                "class_average": 72.3,
                "teacher_comment": "Excellent progress"
            }
        ]
    }
    ```

### **2. Get Subject Performance**
*   **Endpoint**: `GET /api/student/subject-performance/`
*   **Params**: `student_id_number`, `subject`, `term`

---

## **Phase 4: WhatsApp Bot Implementation**

### **Service Logic (`services/progress_report_service.py`)**

```python
class ProgressReportService:
    
    def get_progress_report(self, student_id, term=None):
        """Fetch and format student progress report"""
        
        # 1. Get grades from SMS API
        grades_data = self.sms_client.get_student_grades(
            student_id_number=student_id,
            term=term or self.get_current_term()
        )
        
        # 2. Calculate statistics
        stats = self.calculate_statistics(grades_data)
        
        # 3. Format for WhatsApp
        message = self.format_progress_message(grades_data, stats)
        
        return message
    
    def format_progress_message(self, data, stats):
        """Format grades for WhatsApp display"""
        
        message = f"""
📊 *Progress Report*
Student: {data['student']}
Term: {data['term']}

*Overall Performance*
Average: {stats['overall_avg']:.1f}%
Rank: {stats['rank']} / {stats['total_students']}

*Subject Breakdown:*
"""
        
        for subject in data['grades']:
            message += f"""
📚 *{subject['subject']}*
  Grade: {subject['grade']} ({subject['average']:.1f}%)
  Class Avg: {subject['class_average']:.1f}%
  Teacher: {subject['teacher_comment']}
"""
        return message
```

---

## **Phase 5: User Flow**

1.  **Parent**: Sends "Check grades" or selects from menu.
2.  **Bot**: Asks "Which student?" (if multiple children linked).
3.  **Parent**: Selects student (e.g., "Peace Kuwaza").
4.  **Bot**: Fetches data from API.
5.  **Bot**: Sends formatted text report: "📊 Progress Report...".
6.  **Bot**: Offers follow-up options:
    *   1️⃣ Detailed PDF Report
    *   2️⃣ Subject-specific details
    *   3️⃣ Compare to previous term

---

## **Phase 6: Advanced Features**

### **1. Trend Analysis**
Compare current vs. previous terms to show improvement or decline.
```python
{
    "improvement": +5.5,
    "trend": "improving"  # or "declining", "stable"
}
```

### **2. Smart Alerts**
Automatically notify parents when grades drop significantly.
*   *Example*: "⚠️ Math grade dropped from 85% to 72%. Consider scheduling a meeting."

### **3. Comparison View**
Show student performance relative to the class.
*   *Example*: "Your child: 85% | Class Avg: 72% | Top Score: 95%"

---

## 🛠️ **Implementation Timeline**

*   **Week 1: Backend Setup**
    *   Design database schema.
    *   Create API endpoints in SMS system.
    *   Test endpoints.
*   **Week 2: Teacher Portal (if needed)**
    *   Build grade entry interface.
    *   Test with teachers.
*   **Week 3: Bot Integration**
    *   Create `ProgressReportService`.
    *   Add WhatsApp menu option.
    *   Testing & refinement.
*   **Week 4: Advanced Features**
    *   PDF generation (text-only initially).
    *   Trend analysis.
    *   Smart alerts.

---

## 🔐 **Security Considerations**

1.  **Authentication**: Only linked WhatsApp numbers can view grades.
2.  **Privacy**: Each parent sees only their child's data.
3.  **Audit Trail**: Log all grade access requests.
4.  **Data Validation**: Teachers can only edit their own subject grades.

---

## 📱 **Quick Start (MVP)**

To test with minimal setup:
1.  Add **one API endpoint** (`GET /api/student/grades/`).
2.  **Manual data entry**: Add sample grades for testing.
3.  **Simple bot response**: Text-based summary.
4.  **Test with parents** and iterate.
