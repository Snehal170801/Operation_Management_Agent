from datetime import datetime

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    # approval | case | invoice (staff, need action) | my_request (requester, informational)
    kind: str
    title: str
    message: str
    # An in-app path to open
    link: str
    created_at: datetime
    requires_action: bool
