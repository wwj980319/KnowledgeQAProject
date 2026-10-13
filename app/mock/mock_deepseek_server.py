from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class DeepSeekMockHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        '''
        Mock服务需要监听一个端口，
        收到 POST /chat/completions，
        返回符合 DeepSeek API 规范的 JSON 响应体
        '''
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
    
        content_length = int(self.headers.get("Content-Length", 0))
        raw_data = self.rfile.read(content_length).decode("utf-8")
        raw_data = json.loads(raw_data)

        resp = {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "question": raw_data["messages"][-1]["content"],
                    "content": "【Mock回答】这是一个测试回答"
                }
            }]
        }
        data = json.dumps(resp, ensure_ascii=False).encode()
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

if __name__ == "__main__":
    '''
    启动 DeepSeek 模拟 API服务，监听端口 8001，绑 0.0.0.0：局域网内任何人都能访问
    '''
    server_address = ("0.0.0.0", 8001)
    httpd = HTTPServer(server_address, DeepSeekMockHandler)
    httpd.serve_forever()