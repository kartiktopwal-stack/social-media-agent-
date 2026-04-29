"""
test_scheduler.py
─────────────────────────────────────────────────────────────────────────────
Verify Celery Beat configuration is correct and manually trigger a pipeline run.
"""

from __future__ import annotations

from celery_app import app

def main():
    print("=" * 60)
    print("Celery Beat Configuration Test")
    print("=" * 60)
    
    # Print registered beat schedule
    print("\n[1] Registered Beat Schedule:")
    beat_schedule = app.conf.beat_schedule
    for task_name, config in beat_schedule.items():
        print(f"    Task: {task_name}")
        print(f"      - task: {config['task']}")
        print(f"      - schedule: {config['schedule']}")
        print(f"      - args: {config.get('args', 'None')}")
    
    print(f"\n[2] Timezone: {app.conf.timezone}")
    
    # Queue a manual run
    print("\n[3] Queuing manual pipeline run for ['technology']...")
    from tasks.clip_tasks import run_full_pipeline
    run_full_pipeline.delay(['technology'])
    
    print("Task queued — check empire_worker window for execution")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    main()
