import re
from pathlib import Path
import report_service as rs

payload = {
  'report_variant': 'short',
  'project': {
    'name': 'SMITH STREET CONNECTION ROAD',
    'location': '-',
    'report_date': '2026-05-13',
    'prepared_by': "Planner\'s Name",
    'cc_number': 'CC0000',
  },
  'inputs': {
    'road_operation_mode': 'TWO-WAY',
    'base_year': '2024',
    'opening_year': '2026',
    'base_year_aadt': 73931,
    'opening_year_aadt': 77675,
    'd1_vadt_opening_year': 37096,
    'd2_vadt_opening_year': 40579,
    'growth_rate_percent': 2.5,
  },
  'results': {
    'queue_peak_m': 5396,
    'worst_vcr': 2.42,
    'los': 'F',
    'detour_recommended': True,
  },
  'raw_js_results': {
    'detour_route_count': 1,
    'base_year': '2024',
    'opening_year': '2026',
  },
  'selected_site_details': {
    'site_id': '11545',
    'source': 'TMR',
    'road_name': 'SMITH STREET CONNECTION ROAD',
    'description': 'East of Precision Dr',
    'coordinates': '-27.963128, 153.363311',
    'google_maps_url': 'https://maps.google.com/?q=-27.963128,153.363311',
    'count_year': '2024',
    'd1_direction': 'Eastbound',
    'd2_direction': 'Westbound',
    'd1_vadt': '35,308',
    'd2_vadt': '38,623',
    'total_vadt': '73,931',
    'applied_d1_hv_percent': '7.6',
    'applied_d2_hv_percent': '7.6',
    'applied_d1_rt_percent': '0.15',
    'applied_d2_rt_percent': '0.15',
  },
  'notes': [
    'High Risk Period: AM | Network Max Queue ~= 5,396 m',
    'High Risk Period: AM | Worst VCR = 2.358 (LOS F)',
  ],
  'tables': [
    {'table_id':'analysis_parameters','title':'Analysis Parameters','columns':['Parameter','Value'],'rows':[['ROAD OPERATION MODE','TWO-WAY']]},
    {'table_id':'summary_computed_results','title':'Summary of Computed Results','columns':['Metric','Value'],'rows':[['QUEUE PEAK M','5396'],['WORST VCR','2.42'],['LOS','F'],['DETOUR RECOMMENDED','True']]},
    {'table_id':'groupedtabled1','title':'GROUPED DIRECTIONAL SUMMARY - D1 - DIRECTION 1, GAZETTAL, EASTBOUND','columns':['YEAR','AM LV','TOTAL'],'rows':[['2024','1889','35308'],['2026','1985','37096']]},
    {'table_id':'groupedtabled2','title':'GROUPED DIRECTIONAL SUMMARY - D2 - DIRECTION 2, AGAINST GAZETTAL, WESTBOUND','columns':['YEAR','AM LV','TOTAL'],'rows':[['2024','3327','38623'],['2026','3496','40579']]},
    {'table_id':'queuegroupedtabled1','title':'DIRECTIONAL QUEUE SUMMARY - D1 - DIRECTION 1, GAZETTAL, EASTBOUND','columns':['Metric','AM','OP','PM','EV'],'rows':[['1 Lane Closed (1 open)','4343','3000','3200','1200']]},
    {'table_id':'queuegroupedtabled2','title':'DIRECTIONAL QUEUE SUMMARY - D2 - DIRECTION 2, AGAINST GAZETTAL, WESTBOUND','columns':['Metric','AM','OP','PM','EV'],'rows':[['1 Lane Closed (1 open)','5396','4000','3800','1400']]},
    {'table_id':'queueswtsummarytable','title':'DIRECTIONAL QUEUE SUMMARY - SWT - SWT QUEUE SUMMARY','columns':['Metric','AM','OP','PM','EV'],'rows':[['Queue Peak','1440','800','900','300']]},
    {'table_id':'vcrgroupedtabled1','title':'DIRECTIONAL VCR SUMMARY - D1 - DIRECTION 1, GAZETTAL, EASTBOUND','columns':['Metric','AM','OP','PM','EV'],'rows':[['1 Lane Closed (1 open)','2.25 LOS F','1.50 LOS F','1.40 LOS F','0.50 LOS A']]},
    {'table_id':'vcrgroupedtabled2','title':'DIRECTIONAL VCR SUMMARY - D2 - DIRECTION 2, AGAINST GAZETTAL, WESTBOUND','columns':['Metric','AM','OP','PM','EV'],'rows':[['1 Lane Closed (1 open)','2.36 LOS F','1.65 LOS F','1.59 LOS F','0.58 LOS A']]},
    {'table_id':'detour_route_1_info','title':'1. DETOUR ROUTE INFORMATION','columns':['PARAMETER','DETAILS'],'rows':[['Detour Route Name','Precision Drive >> Smith Street Motorway'],['Selected Path','Precision Drive >> Smith Street Motorway'],['Route Length (km)','5km'],['Road Classification','Urban']]},
    {'table_id':'detour_road_summary','title':'Table 28 - Detour Road Summary','columns':['Direction','LOS','VCR','Capacity (veh/h)','Volume (veh/h)'],'rows':[['D1','F','2.36','1500','3540'],['D2','—','—','—','—']]},
    {'table_id':'detour_route_1_delay','title':'ESTIMATED DELAY - DETOUR ROUTE','columns':['PARAMETER','VALUE'],'rows':[['Detour Route Length (km)','0.4'],['Average Travel Speed on Detour (km/h)','70'],['Travel Time (seconds)','21'],['Total Time incl. Intersections (seconds)','61'],['Estimated Additional Travel Time (min)','2'],['Delay Classification','Moderate (1-5 min)']]},
    {'table_id':'detour_route_1_ped','title':'PEDESTRIAN DETOUR IMPACT INCLUDE IN PRINT: YES - ESTIMATED DELAY - DETOUR ROUTE (PRECISION DRIVE >> SMITH STREET MOTORWAY)','columns':['EXISTING ROUTE TIME (S)','DETOURED ROUTE TIME (S)','CROSSING DELAY (S)','ADDED DELAY (S)','ADDED DELAY (MIN)'],'rows':[['83.34','333.34','120','370','6.17']]},
  ]
}

draft_id = 'a'*32
rs.DRAFTS[draft_id] = {'title':'SMITH STREET CONNECTION ROAD_short python report','payload':payload,'created_at':'2026-05-14T00:00:00Z','created_epoch':__import__('time').time()}
html = rs.editor_page(draft_id)
Path('_generated_short_report.html').write_text(html, encoding='utf-8')

text = re.sub(r'<script[\\s\\S]*?</script>', ' ', html, flags=re.I)
text = re.sub(r'<style[\\s\\S]*?</style>', ' ', text, flags=re.I)
text = re.sub(r'<[^>]+>', '\\n', text)
text = re.sub(r'\\n+', '\\n', text)
text = re.sub(r'[ \t]+', ' ', text)
Path('_generated_short_report_text.txt').write_text(text, encoding='utf-8')
print('generated', len(html), len(text))

