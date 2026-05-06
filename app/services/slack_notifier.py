"""
Slack webhook notification service
"""
import json
import requests
from typing import Optional, Dict
from datetime import datetime
import logging

log = logging.getLogger(__name__)


class SlackConfig:
    """Slack webhook configuration"""
    def __init__(self, webhook_url: str, enabled: bool = True, 
                 notify_on_hot: bool = True, notify_on_warm: bool = False):
        self.webhook_url = webhook_url
        self.enabled = enabled
        self.notify_on_hot = notify_on_hot
        self.notify_on_warm = notify_on_warm
    
    def to_dict(self) -> Dict:
        return {
            'webhook_url': self.webhook_url,
            'enabled': self.enabled,
            'notify_on_hot': self.notify_on_hot,
            'notify_on_warm': self.notify_on_warm
        }


class SlackNotifier:
    """Send notifications to Slack"""
    
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url
        self.enabled = webhook_url is not None and len(webhook_url) > 0
    
    def set_webhook(self, webhook_url: str) -> bool:
        """Set the webhook URL"""
        if not webhook_url or len(webhook_url) == 0:
            self.webhook_url = None
            self.enabled = False
            return False
        
        self.webhook_url = webhook_url
        self.enabled = True
        return True
    
    def test_webhook(self) -> bool:
        """Test if webhook is valid"""
        if not self.enabled or not self.webhook_url:
            return False
        
        try:
            message = {
                "text": "🧪 Test message from AutonomousSDR",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*AutonomousSDR*\nWebhook test successful! ✅"
                        }
                    }
                ]
            }
            
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=5
            )
            return response.status_code == 200
        
        except Exception as e:
            log.error(f"Webhook test failed: {e}")
            return False
    
    def notify_hot_lead(self, lead_data: Dict) -> bool:
        """
        Send notification for Hot lead
        
        Args:
            lead_data: Dictionary with lead information
            
        Returns:
            True if sent successfully
        """
        if not self.enabled or not self.webhook_url:
            return False
        
        try:
            confidence = lead_data.get('confidence_score', 0)
            confidence_pct = round(confidence * 100, 1)
            
            message = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "🔥 HOT LEAD FOUND",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Name:*\n{lead_data.get('name', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Company:*\n{lead_data.get('company', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Email:*\n{lead_data.get('email', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Confidence:*\n{confidence_pct}%"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Title:*\n{lead_data.get('job_title', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Industry:*\n{lead_data.get('industry', 'N/A')}"
                            }
                        ]
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Reasoning:*\n{lead_data.get('reasoning', 'Strong ICP match')}"
                        }
                    }
                ]
            }
            
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=5
            )
            
            if response.status_code != 200:
                log.error(f"Slack notification failed: {response.status_code} - {response.text}")
                return False
            
            return True
        
        except Exception as e:
            log.error(f"Failed to send Slack notification: {e}")
            return False
    
    def notify_warm_lead(self, lead_data: Dict) -> bool:
        """Send notification for Warm lead"""
        if not self.enabled or not self.webhook_url:
            return False
        
        try:
            confidence = lead_data.get('confidence_score', 0)
            confidence_pct = round(confidence * 100, 1)
            
            message = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "☀️ WARM LEAD FOUND",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Name:*\n{lead_data.get('name', 'N/A')}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Company:*\n{lead_data.get('company', 'N/A')}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Confidence:* {confidence_pct}%"
                        }
                    }
                ]
            }
            
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=5
            )
            
            return response.status_code == 200
        
        except Exception as e:
            log.error(f"Failed to send warm lead notification: {e}")
            return False
    
    def notify_import_complete(self, import_result: Dict) -> bool:
        """Send notification for completed import"""
        if not self.enabled or not self.webhook_url:
            return False
        
        try:
            message = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "📊 CSV Import Complete",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Total Records:*\n{import_result.get('total_records', 0)}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Successful:*\n{import_result.get('successful', 0)}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Failed:*\n{import_result.get('failed', 0)}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Duplicates:*\n{import_result.get('duplicates_found', 0)}"
                            }
                        ]
                    }
                ]
            }
            
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=5
            )
            
            return response.status_code == 200
        
        except Exception as e:
            log.error(f"Failed to send import notification: {e}")
            return False
