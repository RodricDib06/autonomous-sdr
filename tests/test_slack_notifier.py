"""
Tests for Slack notifier service
"""
from unittest.mock import patch, MagicMock
from app.services.slack_notifier import SlackNotifier, SlackConfig


def test_slack_config_creation():
    """Test Slack config initialization"""
    config = SlackConfig("https://hooks.slack.com/services/test")
    
    assert config.webhook_url == "https://hooks.slack.com/services/test"
    assert config.enabled is True
    assert config.notify_on_hot is True
    assert config.notify_on_warm is False


def test_slack_config_to_dict():
    """Test Slack config serialization"""
    config = SlackConfig("https://hooks.slack.com/services/test")
    config_dict = config.to_dict()
    
    assert config_dict['webhook_url'] == "https://hooks.slack.com/services/test"
    assert config_dict['enabled'] is True
    assert config_dict['notify_on_hot'] is True


def test_slack_notifier_creation():
    """Test notifier initialization"""
    notifier = SlackNotifier()
    
    assert notifier.enabled is False
    assert notifier.webhook_url is None


def test_slack_notifier_set_webhook():
    """Test setting webhook URL"""
    notifier = SlackNotifier()
    
    success = notifier.set_webhook("https://hooks.slack.com/services/test")
    
    assert success is True
    assert notifier.enabled is True
    assert notifier.webhook_url == "https://hooks.slack.com/services/test"


def test_slack_notifier_clear_webhook():
    """Test clearing webhook URL"""
    notifier = SlackNotifier()
    notifier.set_webhook("https://hooks.slack.com/services/test")
    
    success = notifier.set_webhook(None)
    
    assert success is False
    assert notifier.enabled is False


def test_slack_notifier_empty_webhook():
    """Test handling of empty webhook"""
    notifier = SlackNotifier()
    
    success = notifier.set_webhook("")
    
    assert success is False
    assert notifier.enabled is False


@patch('requests.post')
def test_test_webhook_success(mock_post):
    """Test webhook testing with success"""
    mock_post.return_value = MagicMock(status_code=200)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    result = notifier.test_webhook()
    
    assert result is True
    assert mock_post.called


@patch('requests.post')
def test_test_webhook_failure(mock_post):
    """Test webhook testing with failure"""
    mock_post.return_value = MagicMock(status_code=500)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    result = notifier.test_webhook()
    
    assert result is False


def test_test_webhook_not_configured():
    """Test webhook testing when not configured"""
    notifier = SlackNotifier()
    
    result = notifier.test_webhook()
    
    assert result is False


@patch('requests.post')
def test_notify_hot_lead(mock_post):
    """Test sending hot lead notification"""
    mock_post.return_value = MagicMock(status_code=200)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    
    lead_data = {
        "name": "John Smith",
        "company": "Acme Inc",
        "email": "john@acme.com",
        "confidence_score": 0.95,
        "job_title": "VP Sales",
        "industry": "SaaS",
        "reasoning": "Strong ICP match"
    }
    
    result = notifier.notify_hot_lead(lead_data)
    
    assert result is True
    assert mock_post.called
    
    # Verify the message format
    call_args = mock_post.call_args
    message = call_args[1]['json']
    assert 'blocks' in message


@patch('requests.post')
def test_notify_warm_lead(mock_post):
    """Test sending warm lead notification"""
    mock_post.return_value = MagicMock(status_code=200)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    
    lead_data = {
        "name": "Jane Doe",
        "company": "Tech Corp",
        "confidence_score": 0.70
    }
    
    result = notifier.notify_warm_lead(lead_data)
    
    assert result is True
    assert mock_post.called


@patch('requests.post')
def test_notify_import_complete(mock_post):
    """Test sending import completion notification"""
    mock_post.return_value = MagicMock(status_code=200)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    
    import_result = {
        "total_records": 100,
        "successful": 95,
        "failed": 5,
        "duplicates_found": 0
    }
    
    result = notifier.notify_import_complete(import_result)
    
    assert result is True
    assert mock_post.called


def test_notify_without_webhook():
    """Test that notifications fail gracefully without webhook"""
    notifier = SlackNotifier()  # No webhook configured
    
    lead_data = {"name": "John"}
    result = notifier.notify_hot_lead(lead_data)
    
    assert result is False


@patch('requests.post')
def test_notify_hot_lead_with_defaults(mock_post):
    """Test notification with minimal data"""
    mock_post.return_value = MagicMock(status_code=200)
    
    notifier = SlackNotifier("https://hooks.slack.com/services/test")
    
    # Minimal data
    lead_data = {
        "name": "John Smith",
        "company": "Acme Inc",
        "email": "john@acme.com"
    }
    
    result = notifier.notify_hot_lead(lead_data)
    
    assert result is True
