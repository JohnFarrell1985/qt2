"""EtfDownloadProgress / etf_download_progress 表 基本用例"""

from src.data.etf_download_progress import ETF_SYNC_TYPE_DAILY, EtfDownloadProgressDAO


def test_etf_dao_init_empty():
    assert EtfDownloadProgressDAO.init_progress([], ETF_SYNC_TYPE_DAILY) == 0
