from apscheduler.schedulers.background import BackgroundScheduler
def init_scheduler():
    """Initialize scheduler for balance reminders, payment checks, and profile sync."""
    try:
        scheduler = BackgroundScheduler({
            'apscheduler.job_defaults.max_instances': 1,
        })
        # W2.4: daily profile sync removed — SaaS is the source of truth.
        # Weekly reminders for all students in debt (Monday at 9 AM)
        scheduler.add_job(
            send_all_reminders,
            trigger="cron",
            day_of_week="mon",
            hour=9,
            minute=0,
            id='send_all_reminders',
            replace_existing=True
        )
        # Daily payment checks at 8 AM
        scheduler.add_job(
            check_all_payments,
            trigger="cron",
            hour=8,
            minute=0,
            id='check_all_payments',
            replace_existing=True
        )
        scheduler.start()
        logger.info("Scheduler started")
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}")
        raise