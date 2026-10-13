"""Small explicit rule pack; absence of a violation is not overall compliance."""
import copy
SOURCE='https://ghzrzyw.beijing.gov.cn/biaozhunguanli/bz/szjgdjt/202406/t20240603_3703097.html'

def review(spec):
    notes=[{'category':'norm_pending','code':'scope_incomplete','message':'本包只覆盖少数已核条目，未完成整体规范审查；几何通过不代表规划合规。'}]
    ctx=spec.get('norm_context',{})
    if not isinstance(ctx,dict):return notes
    if ctx.get('jurisdiction')!='Beijing':return notes
    meta={'source':SOURCE,'standard':'DB11/T 1116-2024','clause':'4.6.1; 4.6.2–4.6.4','pdf_page':21,'printed_page':7,'verified_on':'2026-10-12'}
    # Only apply the general branch row when every exception/context question is answered.
    required=['general_urban_section','new_construction','no_high_pedestrian_facility','no_transit_entrance_within_50m','inside_construction_area','no_sparse_pedestrian_side']
    if ctx.get('road_class')!='branch' or spec.get('units')!='m' or not all(ctx.get(k) is True for k in required):
        notes.append({'category':'norm_pending','code':'sidewalk_context_required','message':'支路人行道校核需确认道路等级、米制、新建/改造、建设区、重点人流设施、轨道入口及行人稀少侧等适用条件；当前不自动套用通用限值。','required_context':required,**meta});return notes
    components=spec.get('components',[])
    sidewalks=[c for c in components if c.get('role')=='sidewalk']
    if not sidewalks:notes.append({'category':'norm_pending','code':'sidewalk_components_missing','message':'未提供 role=sidewalk 的横断面组成，不能从道路总宽推算人行道宽度。',**meta})
    for c in sidewalks:
        w=c.get('width')
        if not isinstance(w,(int,float)) or isinstance(w,bool):continue
        category='norm_issue' if w<2 else 'design_tradeoff' if w<3 else 'norm_checked'
        notes.append({'category':category,'code':'branch_sidewalk_width','component':c.get('id',c.get('name')),'width_m':w,'minimum_m':2,'recommended_m':3,'message':'一般支路人行道本条检查；推荐值与最小值分别呈现，适用条件由输入声明。',**meta})
    return notes

def annotate(result):
    result['report']['professional_review']=review(result['spec'])
    result['report']['categories']={'errors':'geometry_error','warnings':'teaching_advice','professional_review':'see_each_item_category'}
    return result
