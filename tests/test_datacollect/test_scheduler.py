"""CollectScheduler 单元测试

测试 src/datacollect/scheduler.py:
- 无 APScheduler 安装时的优雅降级
- add_cron_job / add_interval_job (mock APScheduler)
- start / shutdown 生命周期
- list_jobs
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import sys

from src.datacollect.scheduler import CollectScheduler


@pytest.fixture()
def scheduler():
    return CollectScheduler()


@pytest.fixture()
def mock_bg_scheduler():
    """Mock APScheduler BackgroundScheduler 及触发器"""
    mock_sched_instance = MagicMock()
    mock_sched_instance.running = False
    mock_sched_instance.get_jobs.return_value = []

    mock_bg_cls = MagicMock(return_value=mock_sched_instance)
    mock_cron_trigger = MagicMock()
    mock_interval_trigger = MagicMock()

    patches = {
        "apscheduler.schedulers.background": MagicMock(BackgroundScheduler=mock_bg_cls),
        "apscheduler.triggers.cron": MagicMock(CronTrigger=mock_cron_trigger),
        "apscheduler.triggers.interval": MagicMock(IntervalTrigger=mock_interval_trigger),
        "apscheduler": MagicMock(),
    }

    with patch.dict(sys.modules, patches):
        yield {
            "scheduler_instance": mock_sched_instance,
            "bg_cls": mock_bg_cls,
            "cron_trigger": mock_cron_trigger,
            "interval_trigger": mock_interval_trigger,
        }


class TestInitWithoutAPScheduler:

    @pytest.mark.timeout(30)
    def test_init_no_apscheduler(self):
        sched = CollectScheduler()
        assert sched._scheduler is None
        assert sched._jobs == {}

    @pytest.mark.timeout(30)
    def test_graceful_degradation_on_import_error(self):
        sched = CollectScheduler()

        saved_modules = {}
        mod_names = [k for k in sys.modules if k.startswith("apscheduler")]
        for k in mod_names:
            saved_modules[k] = sys.modules.pop(k)

        fake_modules = {
            "apscheduler": None,
            "apscheduler.schedulers": None,
            "apscheduler.schedulers.background": None,
            "apscheduler.triggers": None,
            "apscheduler.triggers.cron": None,
            "apscheduler.triggers.interval": None,
        }

        with patch.dict(sys.modules, fake_modules):
            sched._ensure_scheduler()
            assert sched._scheduler is None

        sys.modules.update(saved_modules)

    @pytest.mark.timeout(30)
    def test_add_cron_job_returns_false_without_scheduler(self):
        sched = CollectScheduler()
        saved_modules = {}
        mod_names = [k for k in sys.modules if k.startswith("apscheduler")]
        for k in mod_names:
            saved_modules[k] = sys.modules.pop(k)

        fake_modules = {
            "apscheduler": None,
            "apscheduler.schedulers": None,
            "apscheduler.schedulers.background": None,
            "apscheduler.triggers": None,
            "apscheduler.triggers.cron": None,
            "apscheduler.triggers.interval": None,
        }

        with patch.dict(sys.modules, fake_modules):
            result = sched.add_cron_job("test", lambda: None, hour=9)
            assert result is False

        sys.modules.update(saved_modules)


class TestAddCronJob:

    @pytest.mark.timeout(30)
    def test_add_cron_job_success(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_job = MagicMock()
        mock_job.id = "daily_collect"
        mock_inst.add_job.return_value = mock_job

        sched._scheduler = mock_inst

        dummy_fn = MagicMock()
        result = sched.add_cron_job("daily_collect", dummy_fn, hour=9, minute=30)
        assert result is True
        assert "daily_collect" in sched._jobs
        mock_inst.add_job.assert_called_once()

    @pytest.mark.timeout(30)
    def test_add_cron_job_with_day_of_week(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.add_job.return_value = MagicMock(id="weekly")

        sched._scheduler = mock_inst
        result = sched.add_cron_job("weekly", lambda: None, hour=15, minute=0, day_of_week="mon,wed,fri")
        assert result is True


class TestAddIntervalJob:

    @pytest.mark.timeout(30)
    def test_add_interval_job_success(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_job = MagicMock()
        mock_job.id = "heartbeat"
        mock_inst.add_job.return_value = mock_job

        sched._scheduler = mock_inst

        result = sched.add_interval_job("heartbeat", lambda: None, minutes=5)
        assert result is True
        assert "heartbeat" in sched._jobs

    @pytest.mark.timeout(30)
    def test_add_interval_job_returns_false_without_scheduler(self):
        sched = CollectScheduler()
        sched._scheduler = None

        saved_modules = {}
        mod_names = [k for k in sys.modules if k.startswith("apscheduler")]
        for k in mod_names:
            saved_modules[k] = sys.modules.pop(k)

        fake_modules = {
            "apscheduler": None,
            "apscheduler.schedulers": None,
            "apscheduler.schedulers.background": None,
            "apscheduler.triggers": None,
            "apscheduler.triggers.cron": None,
            "apscheduler.triggers.interval": None,
        }

        with patch.dict(sys.modules, fake_modules):
            result = sched.add_interval_job("noop", lambda: None, seconds=10)
            assert result is False

        sys.modules.update(saved_modules)


class TestStartShutdown:

    @pytest.mark.timeout(30)
    def test_start_calls_scheduler_start(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.running = False
        sched._scheduler = mock_inst

        sched.start()
        mock_inst.start.assert_called_once()

    @pytest.mark.timeout(30)
    def test_start_noop_when_already_running(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.running = True
        sched._scheduler = mock_inst

        sched.start()
        mock_inst.start.assert_not_called()

    @pytest.mark.timeout(30)
    def test_stop_calls_shutdown(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.running = True
        sched._scheduler = mock_inst

        sched.stop()
        mock_inst.shutdown.assert_called_once_with(wait=False)

    @pytest.mark.timeout(30)
    def test_stop_noop_when_not_running(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.running = False
        sched._scheduler = mock_inst

        sched.stop()
        mock_inst.shutdown.assert_not_called()

    @pytest.mark.timeout(30)
    def test_stop_noop_when_no_scheduler(self):
        sched = CollectScheduler()
        sched.stop()


class TestListJobs:

    @pytest.mark.timeout(30)
    def test_list_jobs_empty(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.get_jobs.return_value = []
        sched._scheduler = mock_inst

        assert sched.list_jobs() == []

    @pytest.mark.timeout(30)
    def test_list_jobs_returns_info(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]

        mock_job = MagicMock()
        mock_job.id = "daily"
        mock_job.next_run_time = "2026-04-15 09:00:00"
        mock_job.trigger = "cron[hour='9']"
        mock_inst.get_jobs.return_value = [mock_job]
        sched._scheduler = mock_inst

        jobs = sched.list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["id"] == "daily"
        assert "next_run" in jobs[0]
        assert "trigger" in jobs[0]

    @pytest.mark.timeout(30)
    def test_list_jobs_none_scheduler(self):
        sched = CollectScheduler()
        sched._scheduler = None
        assert sched.list_jobs() == []


class TestRemoveJob:

    @pytest.mark.timeout(30)
    def test_remove_existing_job(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        sched._scheduler = mock_inst
        sched._jobs["my_job"] = MagicMock()

        result = sched.remove_job("my_job")
        assert result is True
        mock_inst.remove_job.assert_called_once_with("my_job")
        assert "my_job" not in sched._jobs

    @pytest.mark.timeout(30)
    def test_remove_nonexistent_job(self, mock_bg_scheduler):
        sched = CollectScheduler()
        mock_inst = mock_bg_scheduler["scheduler_instance"]
        mock_inst.remove_job.side_effect = Exception("not found")
        sched._scheduler = mock_inst

        result = sched.remove_job("ghost")
        assert result is False

    @pytest.mark.timeout(30)
    def test_remove_without_scheduler(self):
        sched = CollectScheduler()
        assert sched.remove_job("any") is False
