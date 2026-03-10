import logging
from lynk.server import Lynk, json_response, render_template, send_file, abort

app = Lynk(
    host="0.0.0.0",
    port=8765,
    rate_limit=20,              # max 20 messages per second per client
    max_body_size=1024 * 1024,   # 1 MiB
    debug=True
)

@app.get("/")
async def index(req):
    """Serve the main chat HTML page."""
    print(req.__dict__)
    us = req.query_params.get("username")
    print(us)
    user_data = {
      "username": "ales82owj",
      "prof_name": "AE",
      "room_id": "717vwi1o2k",
      "user_id": "hwi2828w8i",
      "friend_id": "272828vwhwuwu"
    }
    return render_template("tp.html", context={"user_data": user_data})
    
if __name__ == "__main__":
  print("stating app")
  logging.basicConfig(level=logging.INFO)
  app.run()