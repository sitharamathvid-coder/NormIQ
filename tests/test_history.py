
import sys
sys.path.append('.')
from database.db_manager import chat_history_get
history = chat_history_get('nurse_test_001', limit=20)
print(f'Messages found: {len(history)}')
for h in history:
    print(h)
