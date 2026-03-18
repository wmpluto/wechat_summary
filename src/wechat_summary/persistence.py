"""ChatSessionStore for saving and loading ChatSession objects as JSON files."""

import re
from datetime import datetime
from pathlib import Path

from wechat_summary.models import ChatSession


class ChatSessionStore:
    """Store for persisting ChatSession objects to JSON files with Chinese text support."""

    def __init__(self):
        """Initialize ChatSessionStore."""
        pass

    def _sanitize_filename(self, chat_name: str) -> str:
        """
        Sanitize chat name for use in filesystem.

        Removes invalid filesystem characters: <>:"/\\|?*

        Args:
            chat_name: Original chat name (may contain Chinese characters)

        Returns:
            Sanitized chat name safe for filesystem
        """
        # Remove invalid filesystem characters: < > : " / \ | ? *
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', chat_name)
        return sanitized

    def _generate_timestamp_suffix(self) -> str:
        """
        Generate timestamp suffix for filename.

        Returns:
            String in format YYYYMMDD_HHMMSS
        """
        now = datetime.now()
        return now.strftime("%Y%m%d_%H%M%S")

    def save(self, session: ChatSession, output_dir: str = "./output") -> str:
        """
        Save ChatSession to JSON file.

        Args:
            session: ChatSession object to save
            output_dir: Directory to save file in (default: "./output")

        Returns:
            Path to saved file as string
        """
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename: {sanitized_chat_name}_{YYYYMMDD_HHMMSS}.json
        sanitized_name = self._sanitize_filename(session.chat_name)
        timestamp = self._generate_timestamp_suffix()
        filename = f"{sanitized_name}_{timestamp}.json"

        filepath = output_path / filename

        # Save as JSON with ensure_ascii=False for Chinese text and indent=2
        json_str = session.model_dump_json(ensure_ascii=False, indent=2)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_str)

        return str(filepath)

    def load(self, filepath: str) -> ChatSession:
        """
        Load ChatSession from JSON file.

        Args:
            filepath: Path to JSON file

        Returns:
            ChatSession object loaded from file

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If JSON is invalid or doesn't match ChatSession schema
        """
        file_path = Path(filepath)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(file_path, "r", encoding="utf-8") as f:
            json_str = f.read()

        # Use Pydantic's model_validate_json to load and validate
        session = ChatSession.model_validate_json(json_str)

        return session

    def save_partial(self, session: ChatSession, output_dir: str = "./output") -> str:
        """
        Save ChatSession with _partial suffix (for interrupted extractions).

        Args:
            session: ChatSession object to save
            output_dir: Directory to save file in (default: "./output")

        Returns:
            Path to saved file as string
        """
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Generate filename: {sanitized_chat_name}_{YYYYMMDD_HHMMSS}_partial.json
        sanitized_name = self._sanitize_filename(session.chat_name)
        timestamp = self._generate_timestamp_suffix()
        filename = f"{sanitized_name}_{timestamp}_partial.json"

        filepath = output_path / filename

        # Save as JSON with ensure_ascii=False for Chinese text and indent=2
        json_str = session.model_dump_json(ensure_ascii=False, indent=2)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(json_str)

        return str(filepath)
