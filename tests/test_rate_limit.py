import random

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.rate_limit import check_rate_limit


def test_rate_limit_blocks_after_threshold():
    user_id = random.randint(10**8, 10**9)  # 随机 id 防跨测试污染
    for _ in range(settings.rate_limit_per_minute):
        check_rate_limit(user_id)
    with pytest.raises(HTTPException) as exc:
        check_rate_limit(user_id)
    assert exc.value.status_code == 429
