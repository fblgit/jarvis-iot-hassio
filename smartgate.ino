#include <Arduino.h>
#include <WiFi.h>
#include <Update.h>
#include <ArduinoJson.h>
#include "AsyncTCP.h"
#include "ESPAsyncWebServer.h"
#include "AsyncJson.h"
#include <ArduinoOTA.h>
#include <HTTPClient.h>
#include "esp_task_wdt.h"
#include <KeyValueEEPROM.h>
#define KeyValueEEPROM_SIZE 4096
#include <PubSubClient.h>
#include <WiFiUdp.h>
#include <Syslog.h>
#define SYSLOG_SERVER "<YOUR_SYSLOG_SERVER>"
#define SYSLOG_PORT 514
#define DEVICE_HOSTNAME "SmartGate"
#define APP_NAME "SmartGate"
#include <Wire.h>
#include "esp_task_wdt.h"

// Wifi Configuration
const char* kSsid = "<YOUR_WIFI>";  // Put your WIFI SSID here.
const char* kPassword = "<YOUR_PASS>";  // Put your WIFI Password here.
const uint32_t kBaudRate = 115200;

// AutoConfig
const bool cfg_auto = true;
const char* cfg_url = "http://your_jarvis.com/config?host=<THE_IP_OF_THIS_DEVICE>";
const char* ping_url = "http://your_jarvis.com/ping?host=<THE_IP_OF_THIS_DEVICE>";
const char* bell_url = "http://your_jarvis.com/doorBell?secret=<JARVIS_API_KEY>";
const char* token_url = "http://your_jarvis.com/tokens?token=";
const char* log_url = "http://your_jarvis.com/gateStatus";

static JsonObject config;
String header;

// Define Syslog Settings
WiFiUDP syslogUDP;
Syslog slog(syslogUDP, SYSLOG_SERVER, SYSLOG_PORT, DEVICE_HOSTNAME, APP_NAME, LOG_INFO);

// Define OTA Settings
const bool ota_enabled = true;
bool shouldReboot = false;

bool gate_status = false;

void postGateLog() {
  HTTPClient http;
  esp_task_wdt_reset();
  http.begin(log_url);
  http.addHeader("Content-Type", "application/json");
  DynamicJsonDocument jsonPost(256);
  // You need to change this piece..
  jsonPost["secret"] = "<JARVIS_API_KEY>";
  if (gate_status == false) {
    gate_status = true;
    jsonPost["action"] = "OPEN";
  } else {
    jsonPost["action"] = "CLOSE";
    gate_status = false;
  }
  String json_post = "";
  serializeJson(jsonPost, json_post);
  http.POST(json_post);
  slog.log(LOG_INFO, "[INFO] Sent GateStatus POST JSON Endpoint");
  Serial.println("[INFO] postGateLog Completed");
  http.end();
}

void actionGate() {
  int gate_relay_pin = KeyValueEEPROM.get<int>("gate_relay_pin");
  pinMode(gate_relay_pin, OUTPUT);
  Serial.println("[GATE] actionGate START");
  digitalWrite(gate_relay_pin, 1);
  delay(750);
  digitalWrite(gate_relay_pin, 0);
  Serial.println("[GATE] actionGate END");
  // removed this part because hassio was not happy
  //postGateLog();
  slog.log(LOG_INFO, "[GATE] ActionGate END OK");
}

int validToken(String token) {
  HTTPClient http;
  String url = String(token_url) + String(token);
  http.begin(url);
  int httpCode = http.GET();
  slog.log(LOG_INFO, "[GATE] validToken RUN OK");
  http.end();
  esp_task_wdt_reset();
  return httpCode;
}

void actionBell() {
  Serial.println("[GATE] actionBell START");
  HTTPClient http;
  http.begin(bell_url);
  int httpCode = http.GET();
  Serial.println("[GATE] actionBell STOP");
  slog.log(LOG_INFO, "[GATE-BELL] Actoned");
  http.end();
}

void setup() {
  Serial.begin(kBaudRate);
  while (!Serial) {
    delay(50);
  }
  WiFi.begin(kSsid, kPassword);
  Serial.print("[WIFI] Connecting ");
  while (WiFi.status() != WL_CONNECTED) {
    delay(900);
    Serial.print(".");
  }
  IPAddress myAddress = WiFi.localIP();
  Serial.println(myAddress.toString());
  slog.log(LOG_INFO, "[INFO] Fetching JSON Endpoint Config");
  HTTPClient http;
  http.begin(cfg_url);
  http.GET();
  DynamicJsonDocument response(4096);
  deserializeJson(response, http.getStream());
  config = response["config"].as<JsonObject>();
  http.end();
  KeyValueEEPROM.begin();
  for (JsonPair keyValue : config) {
    String k = keyValue.key().c_str();
    // Store to Memory
    bool change_values = false;
    if (KeyValueEEPROM.exists(k)) {
      if (KeyValueEEPROM.get<String>(k) != config[k].as<String>()) {
        Serial.println("[UPDATE] Value " + k + " Has Changed");
        slog.logf(LOG_INFO, "[UPDATE] Value %s >> %s", k, config[k].as<String>());
        change_values = true;
        KeyValueEEPROM.set<String>(k, config[k].as<String>());
      } else {
        Serial.println("[OLD] Value " + k + " >> " + KeyValueEEPROM.get<String>(k));
      }
    } else {
      Serial.println("[NEW] Value " + k + " >> " +  config[k].as<String>());
      slog.logf(LOG_INFO, "[NEW] Value %s >> %s", k, config[k].as<String>());
      change_values = true;
      KeyValueEEPROM.set<String>(k, config[k].as<String>());
    }
    if (change_values == true) {
      KeyValueEEPROM.apply();
    }
  }
  bool web_enabled = false;
  if (KeyValueEEPROM.exists("web")) {
    Serial.println("[PRESENT] Web Server");
    if (KeyValueEEPROM.get<String>("web") == String("true")) {
      bool web_enabled = true;
      int web_port = KeyValueEEPROM.get<int>("web_port");
      Serial.println("[ENABLED] Web Server");
      static AsyncWebServer server(web_port);
      server.on("/clearValues", HTTP_GET, [](AsyncWebServerRequest *request){
        Serial.println("Clearing Stored Values on EEProm");
        KeyValueEEPROM.clear();
        KeyValueEEPROM.apply();
        DynamicJsonDocument jsonResp(256);
        jsonResp["status"] = "CLEARED";
        AsyncResponseStream *response = request->beginResponseStream("application/json");
        serializeJson(jsonResp, *response);;
        request->send(response);
      });
      if (KeyValueEEPROM.exists("gate")) {
          Serial.println("[PRESENT] Smart Gate");
          if (KeyValueEEPROM.get<String>("gate") == String("true")) {
            Serial.println("[ENABLED] SmartGate");
            server.on("/gate", HTTP_GET, [](AsyncWebServerRequest *request){
                Serial.println("[RESTful] >> gate HTTP_GET");
                char IP[] = "xxx.xxx.xxx.xxx";
                request->client()->remoteIP().toString().toCharArray(IP, 16);
                DynamicJsonDocument jsonResp(512);
                if (request->hasParam("token")) {
                  AsyncWebParameter* payload = request->getParam("token");
                  if (validToken(payload->value().c_str()) == 200) {
                    actionGate();
                    //postGateLog();
                    esp_task_wdt_reset();
                    jsonResp["status"] = "VALID TOKEN";
                  } else {
                    jsonResp["status"] = "INVALID TOKEN";
                  }
                } else {
                  jsonResp["status"] = "MISSING TOKEN";
                }
                Serial.println("[GATE] Opening Gate OK");
                //slog.logf(LOG_INFO, "[RESTful] >> gate HTTP_GET by %s", IP);
                AsyncResponseStream *response = request->beginResponseStream("application/json");
                serializeJson(jsonResp, *response);
                response->addHeader("Connection", "close");
                request->send(response);
            });
          }
      }
      if (ota_enabled == true) {
        // You want to change this...
        server.on("/SECRETOTAUPDATEURL", HTTP_GET, [](AsyncWebServerRequest *request){
          request->send(200, "text/html", "<form method='POST' action='/SECRETOTAUPDATEURL' enctype='multipart/form-data'><input type='file' name='update'><input type='submit' value='Update'></form>");
        });
        server.on("/SECRETOTAUPDATEURL", HTTP_POST, [](AsyncWebServerRequest *request){
          shouldReboot = !Update.hasError();
          AsyncWebServerResponse *response = request->beginResponse(200, "text/plain", shouldReboot?"OK":"FAIL");
          response->addHeader("Connection", "close");
          request->send(response);
        },[](AsyncWebServerRequest *request, String filename, size_t index, uint8_t *data, size_t len, bool final){
          if(!index){
            Serial.printf("Update Start: %s\n", filename.c_str());
            //Update.runAsync(true);
            if(!Update.begin((ESP.getFreeSketchSpace() - 0x1000) & 0xFFFFF000)){
              Update.printError(Serial);
            }
          }
          if(!Update.hasError()){
            if(Update.write(data, len) != len){
              Update.printError(Serial);
            }
          }
          if(final){
            if(Update.end(true)){
              Serial.printf("Update Success: %uB\n", index+len);
            } else {
              Update.printError(Serial);
            }
          }
        });
      }
      server.on("/OTAreboot", HTTP_GET, [](AsyncWebServerRequest *request){
        if (shouldReboot == true) {
          ESP.restart();
        }
      });
      server.on("/heap", HTTP_GET, [](AsyncWebServerRequest *request){
        DynamicJsonDocument jsonResp(128);
        AsyncResponseStream *response = request->beginResponseStream("application/json");
        jsonResp["heap_free"] = ESP.getFreeHeap();
        jsonResp["version"] = "1.7";
        serializeJson(jsonResp, *response);
        request->send(response);
      });
      server.begin();
    }
  }
}
int ping_fail = 0;
void sendPing() {
  HTTPClient http;
  http.begin(ping_url);
  int httpResponseCode = http.GET();
  http.end();
  if (httpResponseCode != 200) {
    slog.log(LOG_INFO, "[SMARTGATE] Jarvis httpResponse not 200..");
    ping_fail++;
  }
  // Latest change.. under test.
  if (ping_fail > 10) {
    ESP.restart();
  }
}

bool gate_button = false;
int gate_button_state = 0;
int gate_repeat = 0;
int bell_repeat = 0;
bool gate_bell = false;
int gate_bell_state = 0;
int now;
int last_bell = -20000;
int ping_count = 0;

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    // This part is not working, i see this device going off and not coming back
    // but the button works, so its alive.. its a wifi issue.
    Serial.println("WIFI Disconnected, Restarting");
    delay(5000);
    ESP.restart();
  }
  // Implemented this thing to auto-reboot..
  // this controls the doorbell and if its not online
  // its quite annoying...
  if (ping_count > 300) {
    sendPing();
    ping_count = 0;
  } else {
    ping_count++;
  }
  now = millis();
  if (KeyValueEEPROM.exists("gate")) {
    if (KeyValueEEPROM.get<String>("gate") == String("true")) {
      int gate_button_pin = KeyValueEEPROM.get<int>("gate_button_pin");
      if (gate_button == false) {
        pinMode(gate_button_pin, INPUT_PULLDOWN);
        slog.log(LOG_INFO, "[SMARTGATE] Has been Initialized (BUTTON)");
        gate_button = true;
      }
      int gate_bell_pin = KeyValueEEPROM.get<int>("gate_bell_pin");
      int gate_bell_period = KeyValueEEPROM.get<int>("gate_bell_period");
      if (gate_bell == false) {
        pinMode(gate_bell_pin, INPUT_PULLDOWN);
        slog.log(LOG_INFO, "[SMARTGATE] Has been Initialized (BELL)");
        gate_bell = true;
      }
      gate_bell_state =  digitalRead(gate_bell_pin);
      if ((now - last_bell) > gate_bell_period) {
        if (gate_bell_state == HIGH) {
          slog.log(LOG_INFO, "[SMARTGATE] BELL Has been Activated");
          actionBell();
          last_bell = now;
        } 
      } else {
        if (gate_bell_state == HIGH) {
          Serial.println("[SMARTGATE] BELL Is Being Hammered");
          delay(200);
        }
      }
      gate_button_state = digitalRead(gate_button_pin);
      if (gate_button_state == HIGH) {
        gate_repeat++;
      } else {
        if (gate_repeat >= 3 && gate_repeat <= 20) {
          gate_repeat = 0;
          actionGate();
          postGateLog();
          slog.log(LOG_INFO, "[SMARTGATE] BUTTON Has been Activated");
          delay(1000);
        }
        // Still working on this part.. but got into other things.. so its in the backlog :P
        if (gate_repeat >= 30) {
          gate_repeat = 0;
          actionGate();
          postGateLog();
          Serial.println("[SMARTGATE] AUTO CLOSE Has been Activated");
          slog.log(LOG_INFO, "[SMARTGATE] AUTO CLOSE Has Been Activated");
          delay(20000);
          actionGate();
          postGateLog();
          delay(2000);
        }
        gate_repeat = 0;
      }
    }
  }
  delay(100);
}

